# `DataFrame(x)` for every Otwin audit result. Loaded only when DataFrames is.
module OtwinDataFramesExt

using DataFrames: DataFrames, DataFrame
using Otwin: Otwin, CoverageAudit, MarginRisk, TransferValidation

DataFrames.DataFrame(x::Union{CoverageAudit,MarginRisk,TransferValidation}) =
    DataFrame(Otwin.table(x))

end
