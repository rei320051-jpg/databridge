# CSV数据检查与导入说明

## 输入目录

每个数据集目录包含metadata.json、customers.csv、orders.csv和refunds.csv。字段结构及业务规则见data_dictionary.md。所有演示和异常数据均为虚构数据。

只做检查：

```powershell
.\.venv\Scripts\python.exe scripts/import_dataset.py data\demo --report outputs\demo-quality.json
```

检查通过后创建一个新的数据库：

```powershell
.\.venv\Scripts\python.exe scripts/import_dataset.py data\demo --database outputs\demo-v1.0.sqlite3 --report outputs\demo-quality.json
```

退出码0表示没有错误，退出码2表示存在错误。目标数据库已经存在时会拒绝覆盖。导入先在临时文件中完成全部事务和外键检查，成功后才移动到目标路径；失败不留下可误用的半成品数据库。

## 检查内容

- 必需文件、元数据和CSV表头；
- 必填值、整数金额和严格时间格式；
- 主键重复、外键缺失和数据版本不一致；
- 支付、退款状态与时间/金额是否一致；
- 负金额、非正退款及可配置的大额警告；
- 客户建立、下单、支付、退款申请、完成时间顺序；
- 同订单累计成功退款不超过实付；
- 成功支付和退款事件是否在声明的数据覆盖范围内。

默认大额警告阈值是5,000,000分，即50,000元，配置位于config/data_quality.json。超过阈值是警告，不直接认定业务数据错误；查询结果会带回该质量警告。结构、关系或口径错误会阻止导入。

## 现有数据

- data/small：人工可核对的小型数据，版本small-v0.1。
- data/demo：固定种子生成的演示数据，版本demo-v1.0，包含2,000名客户、20,000个订单和3,492条退款。
- data/anomalies：9个彼此隔离的异常场景；8类错误应阻止导入，1个异常大额场景应带警告导入。

运行 `scripts/generate_datasets.py` 会按固定种子重新生成demo和anomalies目录；manifest.json记录行数和文件SHA-256，便于确认数据没有意外变化。
