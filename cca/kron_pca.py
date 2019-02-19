"""
Implementation of 'Robust (Toeplitz) KronPCA from
"Robust Kronecker Product PCA for Spatio-Temporal Covariance Estimation"
by Kristjan Greenewald and Alfred O. Hero.
Link: https://arxiv.org/abs/1411.1352

I faithfully implemented Algorithms 1 and 2 as described in on p. 14 of the
manuscript. I'm not sure what Eq. 16 is trying to acomplish (it seems...wrong).
My implemntation should do this step correctly (see 'build_p(pt)').
"""

import numpy as np
import scipy.linalg
import collections
import functools

class memoized(object):
   """Decorator. Caches a function's return value each time it is called.
   If called later with the same arguments, the cached value is returned
   (not reevaluated).
   From: https://wiki.python.org/moin/PythonDecoratorLibrary.
   """
   def __init__(self, func):
      self.func = func
      self.cache = {}
   def __call__(self, *args):
      if not isinstance(args, collections.Hashable):
         # uncacheable. a list, for instance.
         # better to not cache than blow up.
         return self.func(*args)
      if args in self.cache:
         return self.cache[args]
      else:
         value = self.func(*args)
         self.cache[args] = value
         return value
   def __repr__(self):
      #Return the function's docstring.
      return self.func.__doc__
   def __get__(self, obj, objtype):
      #Support instance methods.
      return functools.partial(self.__call__, obj)

@memoized
def pv_permutation(ps, pt):
    """Permutation on {0, ..., ps^2*pt^2 - 1} corresponding to
    Pitsianis-VanLoan rearrangement. See pv_rearrange for more
    information on how Pitsianis-VanLoan rearrangement works.

    Parameters
    ----------
    ps : int
        Number of spatial dimensions.
    pt : int
        Number of temporal dimensions.

    Returns
    ----------
    perm : np.ndarray
        perm[i] is the index which the i-th element of A.ravel()
        gets sent to under Pitsianis-VanLoan rearrangement.
    perm_inv : np.ndarray
        The inverse of perm.
    """
    I = np.arange(ps**2 * pt**2, dtype=np.int).reshape((ps*pt, ps*pt))
    I_perm = np.zeros(( pt**2, ps**2 ), dtype=np.int)
    for i in range(pt):
        for j in range(pt):
            row_idx =  i*pt + j
            I_block = I[i*ps:(i+1)*ps, j*ps:(j+1)*ps]
            I_perm[row_idx, :] = I_block.T.reshape((ps**2,)) #this is equivalent to I_block.vectorize
    perm = I_perm.ravel()
    perm_inv = perm.argsort()
    return perm, perm_inv

def pv_rearrange(C, ps, pt):
    """Given a ps*pt-by-ps*pt matrix C, Pitsianis-VanLoan rearrangement
    rearranges C into a pt^2-by-ps^2 matrix C_prime, where each
    row of C_prime is the vectorization of a ps-by-ps submatrix of C.

    For example, if
    C = [[A_11, A_12],
         [A_21, A_22]]
    then the Pitsianis-VanLoan rearrangement of C is
    C_prime = [vec(A_11),
               vec(A_12),
               vec(A_21),
               vec(A_22)].
    Note that the arrangment of the ps-by-ps sub-matrices goes left-to-right
    on the block rows of C, while the vectorization operator goes top-to-bottom
    on the columns of each ps-by-ps sub-matrix.

    Parameters
    ----------
    C : np.ndarray, shape (ps*pt, ps*pt)
        Matrix to rearrange.
    ps : int
        Number of spatial dimensions.
    pt : int
        Number of temporal dimensions.

    Returns
    ----------
    C_prime : np.ndarray, shape (pt^2, ps^2)
        Rearranged matrix.
    """
    perm, _ = pv_permutation(ps, pt)
    C_prime = C.ravel()[perm].reshape((pt**2, ps**2))
    return C_prime

def pv_rearrange_inv(C, ps, pt):
    """Inverts the action of pv_rearrange.

    Parameters
    ----------
    C : np.ndarray, shape (pt^2, ps^2)
        Matrix to un-rearrange.
    ps : int
        Number of spatial dimensions.
    pt : int
        Number of temporal dimensions.

    Returns
    ----------
    C_prime : np.ndarray, shape (ps*pt, ps*pt)
        Un-rearranged matrix.
    """
    _, perm_inv = pv_permutation(ps, pt)
    C_prime = C.ravel()[perm_inv].reshape((ps*pt, ps*pt))
    return C_prime

def soft_sv_threshold(M, lambda_param):
    """Soft singular value thresholding operator.

    Parameters
    ----------
    M : np.ndarray, shape (m, n)
        Matrix whose singular values will be soft-thresholded.
    lambda_param : float
        How much to subtract from each singular value.

    Returns
    ----------
    soft_thresholded_M : np.ndarray, shape (m, n)
        M with soft-thresholded singular values.
    """
    U, s, Vh = scipy.linalg.svd(M, full_matrices=False)
    transformed_svs = np.maximum(s - lambda_param, 0)
    soft_thresholded_M = np.dot(U, np.dot(np.diag(transformed_svs), Vh))
    return soft_thresholded_M

def soft_entrywise_threshold(M, lambda_param):
    """Entrywise soft thresholding operator.

    Parameters
    ----------
    M : np.ndarray, shape (m, n)
        Matrix whose entries values will be soft-thresholded.
    lambda_param : float
        How much to subtract from each entry.

    Returns
    ----------
    soft_thresholded_M : np.ndarray, shape (m, n)
        M with soft-thresholded entries.
    """
    soft_thresholded_M = np.sign(M)*np.maximum(np.abs(M) - lambda_param, 0)
    return soft_thresholded_M

def prox_grad_robust_kron_pca(sample_cov, ps, pt, lambda_L, lambda_S, num_iter, tau):
    """Proximal Gradient algorithm for Robust KronPCA
    (Algorithm 1 from Greenewald et al.).

    Parameters
    ----------
    sample_cov : np.ndarray, shape (ps*pt, ps*pt)
        Sample covariance matrix which will be robustly
        estimated by the algorithm.
    ps : int
        Number of spatial dimensions.
    pt : int
        Number of temporal dimensions.
    lambda_L : float
        Regularization parameter corresponding the nuclear norm
        of the PV-rearranged Kronecker decomposition L.
    lambda_S : float
         Regularization parameter corresponding the l1-norm
        of the PV-rearranged additiive sparse component S.
    num_iter : int
        Number of iterations of gradient descent.
    tau : int OR np.ndarray, shape (num_iter,)
        int case: Step size for th algorithm.
        np.ndarray case: Schedule of step-size values for the algorithm.

    Returns
    ----------
    cov_est : np.ndarray, shape (ps*pt, ps*pt)
        Robust KronPCA estiamte of the sample covariance matrix.
    """
    R = pv_rearrange(sample_cov, ps, pt)

    L_prev = np.copy(R)
    S_prev = np.zeros(R.shape)
    M_prev = L_prev + S_prev

    if not isinstance(tau, np.ndarray):
        tau_vals = np.ones(num_iter)*tau
    else:
        tau_vals = tau

    for k in range(num_iter):
        tau = tau_vals[k]

        L = soft_sv_threshold(M_prev - S_prev, tau*lambda_L)
        S = soft_entrywise_threshold(M_prev - L_prev, tau*lambda_S)
        M = L + S - tau*(L + S - R)

        M_prev, S_prev, L_prev = M, S, L

    cov_est = pv_rearrange_inv(L + S, ps, pt)
    return cov_est

def build_P(pt):
    """Builds a matrix P which maps a pt^2-by-ps^2 PV-rearranged
    version of a matrix M to a (2*pt - 1)-by-ps^2 version of M
    corresponding to its `Toepletz-fied' PV-rearrangment. All of
    the rows of the PV-rearanged version of M which should be the
    same in a Toeplitz matrix are added together in a normalzied fashion.

    Note that Greenewald et al. Eq. (16) is supposed to provide a means
    of building this matrix, but I have no clue that he was going for
    with that formula. The implementation here should be fine.

    Parameters
    ----------
    pt : int
        Number of temporal dimensions.

    Returns
    ----------
    P : np.ndarray, shape (2*ps - 1, ps^2)
        Toeplitz-fying map from pt^2-by-ps^2 a PV-rearranged matrix
        to a (2*ps - 1) PV-rearranged matrix.
    """
    P = np.zeros((2*pt - 1, pt**2))
    idx = np.arange(pt**2).reshape((pt, pt)).T + 1
    for offset in range(-pt+1, pt):
        diag_idx = np.diagonal(idx, offset=offset)
        P[offset+pt-1, diag_idx-1] = 1/np.sqrt(pt - np.abs(offset))
    return P


def prox_grad_robust_toeplitz_kron_pca(sample_cov, ps, pt, lambda_L, lambda_S, tau=0.1, tol=1e-8, max_iter=1000000, stop_cond_interval=20):
    """Proximal Gradient algorithm for Robust KronPCA
    (Algorithm 1 from Greenewald et al.).

    Parameters
    ----------
    sample_cov : np.ndarray, shape (ps*pt, ps*pt)
        Sample covariance matrix which will be robustly
        estimated by the algorithm.
    ps : int
        Number of spatial dimensions.
    pt : int
        Number of temporal dimensions.
    lambda_L : float
        Regularization parameter corresponding the nuclear norm
        of the PV-rearranged Kronecker decomposition L.
    lambda_S : float
         Regularization parameter corresponding the l1-norm
        of the PV-rearranged additiive sparse component S.
    num_iter : int
        Number of iterations of gradient descent.
    tau : int OR np.ndarray, shape (num_iter,)
        int case: Step size for th algorithm.
        np.ndarray case: Schedule of step-size values for the algorithm.

    Returns
    ----------
    cov_est : np.ndarray, shape (ps*pt, ps*pt)
        Robust KronPCA estiamte of the sample covariance matrix.
    """
    P = build_P(pt)
    R = pv_rearrange(sample_cov, ps, pt)
    R_tilde = np.dot(P, R)

    L_tilde_prev = np.copy(R_tilde)
    S_tilde_prev = np.zeros(R_tilde.shape)
    M_tilde_prev = L_tilde_prev + S_tilde_prev

    S_tilde = np.zeros(R_tilde.shape) #init so there's no error

    for k in range(max_iter):

        L_tilde = soft_sv_threshold(M_tilde_prev - S_tilde_prev, tau*lambda_L)
        for j in range(-pt+1, pt):
            cj = 1./np.sqrt(pt - np.abs(j))
            S_tilde[j+pt-1] = soft_entrywise_threshold(M_tilde_prev[j+pt-1]-L_tilde_prev[j+pt-1], tau*lambda_S*cj)
        M_tilde = L_tilde + S_tilde - tau*(L_tilde + S_tilde - R_tilde)

        M_tilde_prev, S_tilde_prev, L_tilde_prev = M_tilde, S_tilde, L_tilde

        if k % stop_cond_interval == 0:
            cov_est = pv_rearrange_inv(np.dot(P.T, L_tilde + S_tilde), ps, pt)
            if k > 0:
                rms_diff = np.sqrt(np.mean((cov_est - cov_est_prev)**2))
                if rms_diff < tol:
                    break
            cov_est_prev = cov_est

    rank = np.linalg.matrix_rank(np.dot(P.T, L_tilde))
    sparsity = np.sum(np.nonzero(S_tilde))/S_tilde.size

    return cov_est, rank, sparsity


def cross_validate_toeplitz_fit(X_with_lags, ps, pt, lambda_L, lambda_S, num_folds=10, tau=0.1, tol=1e-8, max_iter=1000000, stop_cond_interval=20):
    
    fold_size = int(np.floor(len(X_with_lags)/num_folds))
    log_likelihood_vals = np.zeros(num_folds)
    rank_vals = np.zeros(num_folds)
    sparsity_vals = np.zeros(num_folds)
    d = X_with_lags.shape[1]
    
    for cv_iter in range(num_folds):
        
        X_train = np.concatenate((X_with_lags[:cv_iter*fold_size], X_with_lags[(cv_iter+1)*fold_size:]), axis=0)
        X_test = X_with_lags[cv_iter*fold_size : (cv_iter+1)*fold_size]
        
        X_train_ctd = X_train - X_train.mean(axis=0)
        cov_train = np.dot(X_train_ctd.T, X_train_ctd)/len(X_train)
        cov_test = np.dot(X_test.T, X_test)/len(X_test)

        cov_reg_train, rank, sparsity = prox_grad_robust_toeplitz_kron_pca(cov_train, ps, pt, lambda_L, lambda_S,
                                                                           tau=tau, tol=tol, max_iter=max_iter,
                                                                           stop_cond_interval=stop_cond_interval)

        if np.sum(np.abs(cov_reg_train)) < 1e-12:
            log_likelihood_vals[cv_iter] = -np.inf
            rank_vals[cv_iter] = 0
            sparsity_vals[cv_iter] = 0
            continue

        cov_reg_train_inv = np.linalg.inv(cov_reg_train)
        _, log_det_cov_reg_train = np.linalg.slogdet(cov_reg_train)
        
        num_samples = len(X_test)
        log_likelihood = -0.5*num_samples*(d*np.log(2*np.pi) + log_det_cov_reg_train + np.trace(np.dot(cov_reg_train_inv, cov_test)))

        log_likelihood_vals[cv_iter] = log_likelihood
        rank_vals[cv_iter] = rank
        sparsity_vals[cv_iter] = sparsity
        
    return log_likelihood_vals, rank_vals, sparsity_vals



def regularize_cov(X_with_lags, ps, pt, lambda_S_vals, lambda_L_vals, num_folds=10, tau=0.1, tol=1e-8, max_iter=1000000, stop_cond_interval=20):
    
    log_likelihood_vals = np.zeros(( len(lambda_L_vals), len(lambda_S_vals), num_folds ))
    rank_vals = np.zeros(log_likelihood_vals.shape)
    sparsity_vals = np.zeros(log_likelihood_vals.shape)

    err = np.inf

    for lambda_L_idx in range(len(lambda_L_vals)):
        for lambda_S_idx in range(len(lambda_S_vals)):

            lambda_L, lambda_S = lambda_L_vals[lambda_L_idx], lambda_S_vals[lambda_S_idx]
            print(lambda_L, lambda_S)
        
            log_likelihood_vals_cv, rank_vals_cv, sparsity_vals_cv = cross_validate_toeplitz_fit(X_with_lags, ps, pt, lambda_L, lambda_S,
                                                                                                 num_folds=num_folds, tau=tau, tol=tol, max_iter=max_iter,
                                                                                                 stop_cond_interval=stop_cond_interval)
            
            log_likelihood_vals[lambda_L_idx, lambda_S_idx] = log_likelihood_vals_cv
            rank_vals[lambda_L_idx, lambda_S_idx] = rank_vals_cv
            sparsity_vals[lambda_L_idx, lambda_S_idx] = sparsity_vals_cv
    
    mean_ll_vals = np.mean( log_likelihood_vals, axis=2 )
    max_idx = np.unravel_index(mean_ll_vals.argmax(), mean_ll_vals.shape)
    lambda_L_opt, lambda_S_opt = lambda_L_vals[max_idx[0]], lambda_S_vals[max_idx[1]]

    sample_cov = np.cov(X_with_lags.T, bias=True)
    final_cov_reg, _, _ = prox_grad_robust_toeplitz_kron_pca(sample_cov, ps, pt, lambda_L, lambda_S, tau=tau, tol=tol, max_iter=max_iter, stop_cond_interval=stop_cond_interval)
    
    return final_cov_reg, log_likelihood_vals, rank_vals, sparsity_vals





