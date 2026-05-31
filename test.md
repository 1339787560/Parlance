- dim_: dimension，维度表。放相对稳定、用于分类和补充描述的数据，比如渠道、版本、场景、配置字典。你这个项目里已经明确
  有这类表，比如 dim_channel_category、dim_currency_op_config、dim_fin_flow_scene_dict。
- fact_: fact，事实表。放业务事件或明细流水，通常行数大、按时间增长，比如登录、对局、支付、订单、银子流水。可以理解
  成“发生了什么”。
- dm_: data mart，数据集市。通常是面向某个主题或业务方整理后的结果层，介于“原始明细”和“报表直接查询”之间。有时它不是表    前缀，而是库名/schema 名。你项目里 hive_catalog_cdh5.dm.olap_tcy_userapp_d_p_login1st 这里的 dm 就更像是 schema。
- attr_: attribute，属性表。一般存对象属性、标签、扩展字段、画像类信息，比 dim_ 更偏“属性补充”而不是标准业务维度。常见    于用户属性、物品属性、设备属性这类场景。

怎么快速区分

- 看主键和更新方式：
    - dim_ / attr_ 往往按实体主键更新，数据相对稳定。
    - fact_ 往往按事件追加，时间字段最关键。
    - dm_ 往往是汇总、宽表、结果表，服务查询和报表。
- 看用途：
    - dim_: 给别人 join 用的。
    - fact_: 被聚合统计的。
    - dm_: 直接拿来分析或出报表的。
    - attr_: 给实体补属性标签的。