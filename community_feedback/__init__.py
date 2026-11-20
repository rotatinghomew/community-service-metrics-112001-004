"""居民反馈覆盖与服务体验分析。

分析口径（与 DATA.md 对应）：

* 分析单位为案件（事项）。同一居民对不同事项的体验分别计票，不跨事项合并；
  ``respondent`` 仅用于识别同一事项内的重复反馈与更正。
* 漏斗分母严格区分三层：符合邀请条件（eligible）→ 实际送达（delivered）→
  作出评价（responded）。未回应记为“未知”，绝不按零分处理。
* 评价可能被后续评价更正（``supersedes``），仅取更正链头部的有效评价。
* 履约事实只来自 ``cases`` 的办结时间与结果，不以评价替代办结。
* 抽样框架不支持总体推断或样本不足时，只给描述性结论，不生成全体满意度排名。
"""

from .models import (
    Case,
    DataIssue,
    DataValidationError,
    Dataset,
    Invitation,
    Period,
    Response,
)

__version__ = "0.1.0"

__all__ = [
    "Case",
    "Invitation",
    "Response",
    "Period",
    "Dataset",
    "DataIssue",
    "DataValidationError",
    "__version__",
]
