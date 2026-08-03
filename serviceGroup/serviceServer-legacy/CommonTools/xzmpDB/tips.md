DBConnector.py：连接到一个 mysql 数据库
- hostName：后续提供
- userName：chunk283
- 端口：3306
- 密码：后续提供

TQVIP.py：操作数据库表 sqlas_tqvip。该表结构如下：
- key：userID
- value：一个 PB 结构，内容如下：
    - experience	    integer         当前等级经验
    - grade	            integer         当前等级    
    - maxexperience	    integer         历史最高经验
    - maxgrade	        integer         历史最高等级
    - rewardstatus	    map             奖励领取状态，key为等级，value为状态。1表示已领取
    - datetag	        integer         最后一次活跃时间
    - lastshowanigrade	integer         最后一次显示动画的等级
    - isdemoteani	    integer         是否降级动画已播放。1表示已播放
- 注意，所有的 PB 结构都使用 3.5.0 的 protoc 进行编译。你应该选择 3.5.1 版本的 py protobuf