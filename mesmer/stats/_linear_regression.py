import numpy as np
import xarray as xr

from mesmer.core.datatree import _datatree_wrapper
from mesmer.core.utils import (
    _check_dataarray_form,
    _check_dataset_form,
    _to_set,
)


class LinearRegression:
    """Ordinary least squares Linear Regression for xr.DataArray objects."""

    def __init__(self):
        self._params = None

    def fit(
        self,
        predictors: dict[str, xr.DataArray] | xr.Dataset,
        target: xr.DataArray,
        dim: str,
        weights: xr.DataArray | None = None,
        fit_intercept: bool = True,
    ):
        """
        Fit a linear model

        Parameters
        ----------
        predictors : dict of xr.DataArray | xr.Dataset
            A dict of DataArray objects used as predictors or a xr.Dataset, with each
            predictor as DataArray. Each predictor must be 1D and contain `dim`.
        target : xr.DataArray
            Target DataArray. Must be 2D and contain `dim`.
        dim : str
            Dimension along which to fit the polynomials.
        weights : xr.DataArray, default: None.
            Individual weights for each sample. Must be 1D and contain `dim`.
        fit_intercept : bool, default=True
            Whether to calculate the intercept for this model. If set to False, no
            intercept will be used in calculations (i.e. data is expected to be
            centered).
        """

        params = _fit_linear_regression_xr(
            predictors=predictors,
            target=target,
            dim=dim,
            weights=weights,
            fit_intercept=fit_intercept,
        )

        self._params = params

    @_datatree_wrapper
    def predict(
        self,
        predictors: dict[str, xr.DataArray] | xr.DataTree | xr.Dataset,
        exclude: str | set[str] | None = None,
    ) -> xr.Dataset | xr.DataTree:
        """
        Predict using the linear model.

        Parameters
        ----------
        predictors : dict of xr.DataArray | DataTree | xr.Dataset
            Either a dict of ``DataArray`` objects used as predictors with predictor names as keys,
            or a ``xr.Dataset`` where each predictor is a ``DataArray``. Each predictor must be 1D
            and contain ``dim``.
            One can also make predictions for multiple trajectories/scenarios at once, in this case,
            pass a ``xr.DataTree`` where each leaf holds a ``Dataset`` with the predictors for a scenario.
        exclude : str or set of str, default: None
            Set of variables to exclude in the prediction. May include ``"intercept"``
            to initialize the prediction with 0.

        Returns
        -------
        prediction : xr.Dataset | xr.DataTree
            Returns predictions in a Dataset or as DataTree if preds was a DataTree.
        """

        params = self.params

        exclude = _to_set(exclude)

        non_predictor_vars = {"intercept", "weights", "fit_intercept"}
        required_predictors = set(params.data_vars) - non_predictor_vars - exclude
        available_predictors = set(predictors.keys()) - exclude

        if required_predictors - available_predictors:
            missing = sorted(required_predictors - available_predictors)
            missing_preds = "', '".join(missing)
            raise ValueError(f"Missing predictors: '{missing_preds}'")

        if available_predictors - required_predictors:
            superfluous = sorted(map(str, available_predictors - required_predictors))
            superfluous_preds = "', '".join(superfluous)
            raise ValueError(
                f"Superfluous predictors: '{superfluous_preds}', either params",
                "for this predictor are missing or you forgot to add it to 'exclude'.",
            )

        if "intercept" in exclude:
            prediction = xr.zeros_like(params.intercept)
        else:
            prediction = params.intercept

        for key in required_predictors:

            signal = predictors[key] * params[key]

            signal = signal.transpose()

            prediction = signal + prediction

        return xr.Dataset({"prediction": prediction})

    def residuals(
        self,
        predictors: dict[str, xr.DataArray] | xr.Dataset,
        target: xr.DataArray,
    ) -> xr.DataArray:
        """
        Calculate the residuals of the fitted linear model

        Parameters
        ----------
        predictors : dict of xr.DataArray | xr.Dataset
            A dict of DataArray objects used as predictors or a Dataset, having each
            predictor as a DataArray. Each predictor must be 1D and contain `dim`.
        target : xr.DataArray
            Target DataArray. Must be 2D and contain `dim`.

        Returns
        -------
        residuals : xr.DataArray
            Returns residuals - the difference between the predicted values and target.

        """

        prediction = self.predict(predictors)

        residuals = target - prediction.prediction

        return residuals.rename("residuals")

    @property
    def params(self):
        """The parameters of this estimator."""

        if self._params is None:
            raise ValueError(
                "'params' not set - call `fit` or assign them to "
                "`LinearRegression().params`."
            )

        return self._params

    @params.setter
    def params(self, params):
        """The parameters of this estimator."""

        _check_dataset_form(
            params,
            "params",
            required_vars={"intercept", "fit_intercept"},
            optional_vars="weights",
            requires_other_vars=True,
        )

        self._params = params

    @classmethod
    def from_netcdf(cls, filename: str, **kwargs):
        """read params from a netCDF file

        Parameters
        ----------
        filename : str
            Name of the netCDF file to open.
        **kwargs : Any
            Additional keyword arguments passed to ``xr.open_dataset``
        """
        ds = xr.open_dataset(filename, **kwargs)

        obj = cls()
        obj.params = ds

        return obj

    def to_netcdf(self, filename: str, **kwargs):
        """save params to a netCDF file

        Parameters
        ----------
        filename : str
            Name of the netCDF file to save.
        **kwargs : Any
            Additional keyword arguments passed to ``xr.Dataset.to_netcf``
        """

        params = self.params
        params.to_netcdf(filename, **kwargs)


def _fit_linear_regression_xr(
    predictors: dict[str, xr.DataArray] | xr.Dataset,
    target: xr.DataArray,
    dim: str,
    weights: xr.DataArray | None = None,
    fit_intercept: bool = True,
) -> xr.Dataset:
    """
    Perform a linear regression

    Parameters
    ----------
    predictors : dict of xr.DataArray | xr.Dataset
        A dict of DataArray objects used as predictors or a xr.Dataset with each
        predictor as DataArray. Each predictor must be 1D and contain `dim`.
    target : xr.DataArray
        Target DataArray. Must be 2D and contain `dim`.
    dim : str
        Dimension along which to fit the polynomials.
    weights : xr.DataArray, default: None.
        Individual weights for each sample. Must be 1D and contain `dim`.
    fit_intercept : bool, default=True
        Whether to calculate the intercept for this model. If set to False, no intercept
        will be used in calculations (i.e. data is expected to be centered).

    Returns
    -------
    :obj:`xr.Dataset`
        Dataset of intercepts and coefficients. The intercepts and each predictor is an
        individual DataArray.
    """
    if not isinstance(predictors, dict | xr.Dataset):
        raise TypeError(
            f"predictors should be a dict or xr.Dataset, got {type(predictors)}."
        )

    if ("weights" in predictors) or ("intercept" in predictors):
        raise ValueError(
            "A predictor with the name 'weights' or 'intercept' is not allowed"
        )

    if dim == "predictor":
        raise ValueError("dim cannot currently be 'predictor'.")

    for key, pred in predictors.items():
        _check_dataarray_form(pred, ndim=1, required_dims=dim, name=f"predictor: {key}")

    if isinstance(predictors, dict | xr.Dataset):
        predictors_concat = xr.concat(
            tuple(predictors.values()),
            dim="predictor",
            join="exact",
            coords="minimal",
        )
        predictors_concat = predictors_concat.assign_coords(
            {"predictor": list(predictors.keys())}
        )

    _check_dataarray_form(target, required_dims=dim, name="target")

    if target.ndim == 1:
        # a 2D target array is required, extra dim is squeezed at the end
        extra_dim = f"__{dim}__"
        target = target.expand_dims(extra_dim)
    elif target.ndim != 2:
        raise ValueError(f"target should be 1D or 2D, but has {target.ndim}D")

    # ensure `dim` is equal
    xr.align(predictors_concat, target, join="exact")

    if weights is not None:
        _check_dataarray_form(weights, ndim=1, required_dims=dim, name="weights")
        xr.align(weights, target, join="exact")

    (target_dim,) = list(set(target.dims) - {dim})

    out = _fit_linear_regression_np(
        predictors_concat.transpose(dim, "predictor"),
        target.transpose(dim, target_dim),
        weights,
        fit_intercept,
    )

    # remove (non-dimension) coords from target (#332, #333)
    target = target.drop_vars(target[dim].coords)

    # split `out` into individual DataArrays
    keys = ["intercept"] + list(predictors_concat.coords["predictor"].values)
    data_vars = {key: (target_dim, out[:, i]) for i, key in enumerate(keys)}
    out = xr.Dataset(data_vars, coords=target.coords)

    out["fit_intercept"] = fit_intercept

    if weights is not None:
        out["weights"] = weights

    return out.squeeze()


def _fit_linear_regression_np(predictors, target, weights=None, fit_intercept=True):
    """
    Perform a linear regression - numpy wrapper

    Parameters
    ----------
    predictors : array-like of shape (n_samples, n_predictors)
        Array of predictors
    target : array-like of shape (n_samples, n_targets)
        Array of targets where each row is a sample and each column is a
        different target i.e. variable to be predicted
    weights : array-like of shape (n_samples,)
        Weights for each sample
    fit_intercept : bool, default=True
        Whether to calculate the intercept for this model. If set to False, no intercept
        will be used in calculations (i.e. data is expected to be centered).

    Returns
    -------
    :obj:`np.ndarray` of shape (n_targets, n_predictors + 1)
        Array of intercepts and coefficients. Each row is the intercept and
        coefficients for a different target (rows are in same order as the
        columns of ``target``). In each row, the intercept of the regression is
        followed by the intercept for each predictor (in the same order as the
        columns of ``predictors``).
    """

    from sklearn.linear_model import LinearRegression

    reg = LinearRegression(fit_intercept=fit_intercept)
    reg.fit(X=predictors, y=target, sample_weight=weights)

    intercepts = np.atleast_2d(reg.intercept_).T
    coefficients = np.atleast_2d(reg.coef_)

    # necessary when fit_intercept = False
    if not fit_intercept:
        intercepts = np.zeros_like(coefficients[:, :1])

    return np.hstack([intercepts, coefficients])
