"""Data layer constants

Constants provided:
- DATASET_NAME:             the open dataset every view derives from
- ENV_DEPARTMENT:           env var naming the department of a skill run
- ENV_DATA_PATH:            env var holding the view path of a skill run
- MAX_RESULT_ROWS:          max rows in one skill result                         default 25
- DEFAULT_LIMIT:            default row limit of ranked results                  default 10
- DEFAULT_TOP_GROUPS:       default series count of grouped trends               default 5
- MAX_TOP_GROUPS:           max series count of grouped trends                   default 8
- MAX_GROUP_BY:             max group-by columns of aggregate-query              default 2
- UNCHANGED_TOLERANCE:      relative change treated as unchanged                 default 0.1%
- DEFAULT_Z_THRESHOLD:      default |z| flagging an anomaly                      default 2.0
- MIN_ANOMALY_PERIODS:      fewest periods needed to score anomalies            default 6
- CLOSURE_MIN_DAYS:         calendar gap without trading reported as a closure   default 5
- MAX_SUGGESTIONS:          close matches offered for an unknown value           default 5
- DENIAL_MESSAGE:           the answer to any raw-data export request (PRD §9)
"""


DATASET_NAME = "UCI Online Retail II"

# cli.py：shell_executor 通过环境变量告诉脚本是哪个部门、数据在哪，模型看不到也传不进来
ENV_DEPARTMENT = "DEPT_NAME"
ENV_DATA_PATH = "DEPT_DATA_PATH"

# policy.py / skills
MAX_RESULT_ROWS = 25
DEFAULT_LIMIT = 10
DEFAULT_TOP_GROUPS = 5
MAX_TOP_GROUPS = 8
MAX_GROUP_BY = 2
UNCHANGED_TOLERANCE = 0.001
DEFAULT_Z_THRESHOLD = 2.0
MIN_ANOMALY_PERIODS = 6

# periods.py：超过这么多天没有交易就算一次停业（例如圣诞假期）
CLOSURE_MIN_DAYS = 5

# filters.py
MAX_SUGGESTIONS = 5

DENIAL_MESSAGE = (
    "Access denied. Raw {record_label} data cannot be exported from this device. "
    "I can provide aggregate {department} insights instead."
)
