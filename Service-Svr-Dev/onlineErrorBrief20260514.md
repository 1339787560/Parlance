线上问题：银子版血流玩法（xzmo2，即 xzmo 的 deposit 版本） 房间不开局，机器人频繁进出房间，当日对局人次为零。
1. 客户端观察：机器人玩家反复退出进入。
2. 客户端观察：桌子 人满不开局。
3. 客户端旁观已开局的桌子时，提示 游戏还没有准备好，请稍后再旁观。
4. 服务端日志：出现问题期间，该房间大量出现日志，打印频率每秒： EnterGame Failed. table,chair is changed in room(15787). userid(222759590), Room table,chair is (-1,-1), gamesvr is (1,3)。重启后几乎没有该日志。
5. 一个房间服务器对应四个房间（初级，高级，大师，宗师房间），其中仅某一个房间（高级房）出现该问题。每个房间的机器人用量为 20 人，桌子数量为 300 桌，四个房间总体玩家不超过 200 人。对于高级房，早上10点到晚上11点的对局人次通常在 100 人左右，而其他时则保持在 10-70 人左右。
6. 事发当天，高级场全天对局人次为0；初级场、大师场 比较前七日明显下降。
7. roomsvrxzmo 是血流血战通用的房间服。线上分别为血流场、血战场部署了房间服，血战房间服务器几乎没怎么出过问题，血流房间服务器大概每月都有一次这个情况。
SVN地址：https://192.168.1.144/svn/xzmoPC/tags/v9.3.20230821_deposit/roomsvrxzmo

注：
血流玩法高级场房间服务 rangeAllocConfig 配置如下：
[Range_15787]
enable=1
Interval=1000
MaxFullRobotTable=2
RobotCountCheck=1
Robot_Clear=2

MaxRange=3
Range_0=20000
Range_1=30000
Range_2=50000
Range_3=70001

UppRange=3000
LowRange=4000

Robot_1=10000
Robot_2=15000
AllRange=8000
Robot_3=25000


以下是重启前和重启后的日志信息
restart before
05/13/26 19:52:50:279[10896][DEBUG][SimpleSubClient.cpp:120] OnlineClient::OnPlayerlogoff: 259567363 
05/13/26 19:52:50:388[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759590(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:50:388[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759595============= 
05/13/26 19:52:50:388[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759584(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:50:388[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759590============= 
05/13/26 19:52:50:389[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759595(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:50:389[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759584============= 
05/13/26 19:52:50:393[9036][DEBUG][RobotRoomData.cpp:470] [ROBOT]__nUserID=95275186, nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 19:52:50:393[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759545(机器人), nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 19:52:50:394[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222634923(机器人), nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 19:52:50:588[11608][WARN][MainOpenServer.cpp:726] EnterGame Failed. table,chair is changed in room(15787). userid(222759590), Room table,chair is (-1,-1), gamesvr is (4,1). 
05/13/26 19:52:50:589[11608][WARN][MainOpenServer.cpp:818] LeaveGameOKVerified user[222759590] status[11] not right. 
05/13/26 19:52:50:982[9168][DEBUG][PlayerData.cpp:84] OnUpdateRobotMatchUserDataRet: 294216043 
05/13/26 19:52:51:401[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759590(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:51:401[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759595============= 
05/13/26 19:52:51:401[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759584(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:51:401[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759590============= 
05/13/26 19:52:51:402[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759595(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:51:402[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759584============= 
05/13/26 19:52:51:406[9036][DEBUG][RobotRoomData.cpp:470] [ROBOT]__nUserID=95275186, nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 19:52:51:406[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759545(机器人), nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 19:52:51:407[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222634923(机器人), nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 19:52:51:449[11608][WARN][MainOpenServer.cpp:726] EnterGame Failed. table,chair is changed in room(15787). userid(222759584), Room table,chair is (-1,-1), gamesvr is (4,1). 
05/13/26 19:52:51:450[11608][WARN][MainOpenServer.cpp:818] LeaveGameOKVerified user[222759584] status[11] not right. 
05/13/26 19:52:52:416[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759590(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:52:416[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759595============= 
05/13/26 19:52:52:416[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759584(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:52:416[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759590============= 
05/13/26 19:52:52:417[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759595(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:52:417[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759584============= 
05/13/26 19:52:52:421[9036][DEBUG][RobotRoomData.cpp:470] [ROBOT]__nUserID=95275186, nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 19:52:52:421[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759545(机器人), nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 19:52:52:422[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222634923(机器人), nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 19:52:52:509[11608][WARN][MainOpenServer.cpp:726] EnterGame Failed. table,chair is changed in room(15787). userid(222759590), Room table,chair is (-1,-1), gamesvr is (4,1). 
05/13/26 19:52:52:510[11608][WARN][MainOpenServer.cpp:818] LeaveGameOKVerified user[222759590] status[11] not right. 
05/13/26 19:52:52:711[11608][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222634916(机器人), nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 19:52:52:712[11608][DEBUG][RobotRoomData.cpp:470] [ROBOT]__nUserID=95275186, nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 19:52:52:712[11608][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759545(机器人), nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 19:52:52:713[11608][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222634923(机器人), nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 19:52:52:713[11608][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222634916(机器人), nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 19:52:53:238[10896][DEBUG][SimpleSubClient.cpp:120] OnlineClient::OnPlayerlogoff: 240966982 
05/13/26 19:52:53:430[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759590(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:53:430[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759595============= 
05/13/26 19:52:53:430[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759584(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:53:430[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759590============= 
05/13/26 19:52:53:431[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759595(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:53:431[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759584============= 
05/13/26 19:52:53:671[11608][WARN][MainOpenServer.cpp:726] EnterGame Failed. table,chair is changed in room(15787). userid(222759590), Room table,chair is (-1,-1), gamesvr is (4,1). 
05/13/26 19:52:53:672[11608][WARN][MainOpenServer.cpp:818] LeaveGameOKVerified user[222759590] status[11] not right. 
05/13/26 19:52:54:440[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759590(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:54:440[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759595============= 
05/13/26 19:52:54:440[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759584(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:54:440[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759590============= 
05/13/26 19:52:54:441[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759595(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:54:441[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759584============= 
05/13/26 19:52:54:473[11608][WARN][MainOpenServer.cpp:726] EnterGame Failed. table,chair is changed in room(15787). userid(222759590), Room table,chair is (-1,-1), gamesvr is (4,1). 
05/13/26 19:52:54:474[11608][WARN][MainOpenServer.cpp:818] LeaveGameOKVerified user[222759590] status[11] not right. 
05/13/26 19:52:54:561[10896][DEBUG][SimpleSubClient.cpp:110] OnlineClient::OnPlayerlogin: 242508811 
05/13/26 19:52:54:573[9168][DEBUG][PlayerData.cpp:115] OnQueryRobotMatchUserDataRet: 242508811 
05/13/26 19:52:54:832[10896][DEBUG][SimpleSubClient.cpp:120] OnlineClient::OnPlayerlogoff: 270801958 
05/13/26 19:52:55:031[10896][DEBUG][SimpleSubClient.cpp:110] OnlineClient::OnPlayerlogin: 273346907 
05/13/26 19:52:55:040[9168][DEBUG][PlayerData.cpp:115] OnQueryRobotMatchUserDataRet: 273346907 
05/13/26 19:52:55:180[10896][DEBUG][SimpleSubClient.cpp:120] OnlineClient::OnPlayerlogoff: 300792669 
05/13/26 19:52:55:450[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759590(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:55:450[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759595============= 
05/13/26 19:52:55:450[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759584(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:55:450[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759590============= 
05/13/26 19:52:55:451[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759595(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:55:451[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759584============= 
05/13/26 19:52:55:484[11608][WARN][MainOpenServer.cpp:726] EnterGame Failed. table,chair is changed in room(15787). userid(222759584), Room table,chair is (-1,-1), gamesvr is (4,1). 
05/13/26 19:52:55:485[11608][WARN][MainOpenServer.cpp:818] LeaveGameOKVerified user[222759584] status[11] not right. 
05/13/26 19:52:56:039[10896][DEBUG][SimpleSubClient.cpp:110] OnlineClient::OnPlayerlogin: 273346907 
05/13/26 19:52:56:049[9168][DEBUG][PlayerData.cpp:115] OnQueryRobotMatchUserDataRet: 273346907 
05/13/26 19:52:56:321[10896][DEBUG][SimpleSubClient.cpp:120] OnlineClient::OnPlayerlogoff: 294961536 
05/13/26 19:52:56:460[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759590(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:56:460[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759595============= 
05/13/26 19:52:56:460[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759584(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:56:460[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759590============= 
05/13/26 19:52:56:461[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759595(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:56:461[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759584============= 
05/13/26 19:52:56:500[11608][WARN][MainOpenServer.cpp:726] EnterGame Failed. table,chair is changed in room(15787). userid(222759590), Room table,chair is (-1,-1), gamesvr is (4,1). 
05/13/26 19:52:56:501[11608][WARN][MainOpenServer.cpp:818] LeaveGameOKVerified user[222759590] status[11] not right. 
05/13/26 19:52:57:209[9168][DEBUG][PlayerData.cpp:84] OnUpdateRobotMatchUserDataRet: 198841386 
05/13/26 19:52:57:470[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759590(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:57:470[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759595============= 
05/13/26 19:52:57:470[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759584(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:57:470[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759590============= 
05/13/26 19:52:57:471[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759595(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:57:471[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759584============= 
05/13/26 19:52:57:497[10896][DEBUG][SimpleSubClient.cpp:120] OnlineClient::OnPlayerlogoff: 299129232 
05/13/26 19:52:57:506[11608][WARN][MainOpenServer.cpp:726] EnterGame Failed. table,chair is changed in room(15787). userid(222759595), Room table,chair is (-1,-1), gamesvr is (4,1). 
05/13/26 19:52:57:507[11608][WARN][MainOpenServer.cpp:818] LeaveGameOKVerified user[222759595] status[11] not right. 
05/13/26 19:52:57:832[10896][DEBUG][SimpleSubClient.cpp:110] OnlineClient::OnPlayerlogin: 242508811 
05/13/26 19:52:57:841[9168][DEBUG][PlayerData.cpp:115] OnQueryRobotMatchUserDataRet: 242508811 
05/13/26 19:52:58:220[9168][DEBUG][PlayerData.cpp:84] OnUpdateRobotMatchUserDataRet: 258054575 
05/13/26 19:52:58:482[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759590(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:58:482[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759595============= 
05/13/26 19:52:58:482[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759584(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:58:482[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759590============= 
05/13/26 19:52:58:483[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759595(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:58:483[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759584============= 
05/13/26 19:52:58:712[11608][WARN][MainOpenServer.cpp:726] EnterGame Failed. table,chair is changed in room(15787). userid(222759584), Room table,chair is (-1,-1), gamesvr is (4,1). 
05/13/26 19:52:58:712[11608][WARN][MainOpenServer.cpp:818] LeaveGameOKVerified user[222759584] status[11] not right. 
05/13/26 19:52:59:110[11608][DEBUG][RobotRoomData.cpp:865] [ROBOT] insert m_mapRobotDelayLeave USERID:222634915, time: 6 
05/13/26 19:52:59:110[11608][DEBUG][RobotRoomData.cpp:865] [ROBOT] insert m_mapRobotDelayLeave USERID:222634924, time: 6 
05/13/26 19:52:59:110[11608][DEBUG][RobotRoomData.cpp:865] [ROBOT] insert m_mapRobotDelayLeave USERID:222759520, time: 8 
05/13/26 19:52:59:146[9168][DEBUG][PlayerData.cpp:84] OnUpdateRobotMatchUserDataRet: 257361335 
05/13/26 19:52:59:169[10896][DEBUG][SimpleSubClient.cpp:110] OnlineClient::OnPlayerlogin: 216524150 
05/13/26 19:52:59:179[9168][DEBUG][PlayerData.cpp:115] OnQueryRobotMatchUserDataRet: 216524150 
05/13/26 19:52:59:252[11608][DEBUG][RobotRoomData.cpp:470] [ROBOT]__nUserID=303719610, nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:59:252[11608][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759595============= 
05/13/26 19:52:59:271[11608][DEBUG][RobotRoomData.cpp:470] [ROBOT]__nUserID=280856007, nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:59:272[11608][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=303719610============= 
05/13/26 19:52:59:310[10896][DEBUG][SimpleSubClient.cpp:110] OnlineClient::OnPlayerlogin: 216524150 
05/13/26 19:52:59:330[9168][DEBUG][PlayerData.cpp:115] OnQueryRobotMatchUserDataRet: 216524150 
05/13/26 19:52:59:491[9036][DEBUG][RobotRoomData.cpp:470] [ROBOT]__nUserID=280856007, nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:59:491[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759590(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:59:491[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=280856007============= 
05/13/26 19:52:59:492[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759584(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:59:492[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759590============= 
05/13/26 19:52:59:492[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759595(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:52:59:492[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759584============= 
05/13/26 19:52:59:653[11608][WARN][MainOpenServer.cpp:726] EnterGame Failed. table,chair is changed in room(15787). userid(222759584), Room table,chair is (-1,-1), gamesvr is (4,1). 
05/13/26 19:52:59:653[11608][WARN][MainOpenServer.cpp:818] LeaveGameOKVerified user[222759584] status[11] not right. 
05/13/26 19:52:59:987[10896][DEBUG][SimpleSubClient.cpp:110] OnlineClient::OnPlayerlogin: 289925485 
05/13/26 19:52:59:997[9168][DEBUG][PlayerData.cpp:115] OnQueryRobotMatchUserDataRet: 289925485 
05/13/26 19:53:00:483[10896][DEBUG][SimpleSubClient.cpp:120] OnlineClient::OnPlayerlogoff: 266264010 
05/13/26 19:53:00:503[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759590(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:53:00:503[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759595============= 
05/13/26 19:53:00:503[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759584(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:53:00:504[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759590============= 
05/13/26 19:53:00:504[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759595(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:53:00:504[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759584============= 
05/13/26 19:53:00:538[11608][WARN][MainOpenServer.cpp:726] EnterGame Failed. table,chair is changed in room(15787). userid(222759595), Room table,chair is (-1,-1), gamesvr is (4,1). 
05/13/26 19:53:00:539[11608][WARN][MainOpenServer.cpp:818] LeaveGameOKVerified user[222759595] status[11] not right. 
05/13/26 19:53:00:687[10896][DEBUG][SimpleSubClient.cpp:120] OnlineClient::OnPlayerlogoff: 269666982 
05/13/26 19:53:01:514[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759590(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:53:01:514[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759595============= 
05/13/26 19:53:01:514[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759584(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:53:01:514[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759590============= 
05/13/26 19:53:01:515[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759595(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:53:01:515[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759584============= 
05/13/26 19:53:01:591[11608][WARN][MainOpenServer.cpp:726] EnterGame Failed. table,chair is changed in room(15787). userid(222759595), Room table,chair is (-1,-1), gamesvr is (4,1). 
05/13/26 19:53:01:592[11608][WARN][MainOpenServer.cpp:818] LeaveGameOKVerified user[222759595] status[11] not right. 
05/13/26 19:53:01:964[11608][DEBUG][RobotRoomData.cpp:470] [ROBOT]__nUserID=304031421, nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:53:01:964[11608][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759595============= 
05/13/26 19:53:02:087[10896][DEBUG][SimpleSubClient.cpp:110] OnlineClient::OnPlayerlogin: 185624791 
05/13/26 19:53:02:097[9168][DEBUG][PlayerData.cpp:115] OnQueryRobotMatchUserDataRet: 185624791 
05/13/26 19:53:02:341[9168][DEBUG][PlayerData.cpp:84] OnUpdateRobotMatchUserDataRet: 115844379 
05/13/26 19:53:02:523[9036][DEBUG][RobotRoomData.cpp:470] [ROBOT]__nUserID=304031421, nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:53:02:523[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759590(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:53:02:523[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=304031421============= 
05/13/26 19:53:02:524[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759584(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:53:02:524[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759590============= 
05/13/26 19:53:02:524[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759595(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:53:02:524[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759584============= 
05/13/26 19:53:02:559[11608][WARN][MainOpenServer.cpp:726] EnterGame Failed. table,chair is changed in room(15787). userid(222759590), Room table,chair is (-1,-1), gamesvr is (4,1). 
05/13/26 19:53:02:559[11608][WARN][MainOpenServer.cpp:818] LeaveGameOKVerified user[222759590] status[11] not right. 
05/13/26 19:53:02:644[10896][DEBUG][SimpleSubClient.cpp:110] OnlineClient::OnPlayerlogin: 185624791 
05/13/26 19:53:02:654[9168][DEBUG][PlayerData.cpp:115] OnQueryRobotMatchUserDataRet: 185624791 
05/13/26 19:53:03:038[10896][DEBUG][SimpleSubClient.cpp:110] OnlineClient::OnPlayerlogin: 185624791 
05/13/26 19:53:03:048[9168][DEBUG][PlayerData.cpp:115] OnQueryRobotMatchUserDataRet: 185624791 
05/13/26 19:53:03:163[10896][DEBUG][SimpleSubClient.cpp:110] OnlineClient::OnPlayerlogin: 185624791 
05/13/26 19:53:03:172[9168][DEBUG][PlayerData.cpp:115] OnQueryRobotMatchUserDataRet: 185624791 
05/13/26 19:53:03:533[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759590(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:53:03:533[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759595============= 
05/13/26 19:53:03:534[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759584(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:53:03:534[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759590============= 
05/13/26 19:53:03:534[9036][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759595(机器人), nFixTable=1, 虚拟桌号nTableNO=4011 
05/13/26 19:53:03:534[9036][WARN][RobotRoomData.cpp:1116] =========== SetRandom Position,tab:4011 chair[0]=222759584============= 
05/13/26 19:53:03:567[11608][WARN][MainOpenServer.cpp:726] EnterGame Failed. table,chair is changed in room(15787). userid(222759584), Room table,chair is (-1,-1), gamesvr is (4,1). 


restart after
05/13/26 19:53:03:568[11608][WARN][MainOpenServer.cpp:818] LeaveGameOKVerified user[222759584] status[11] not right. 
05/13/26 22:52:00:355[11336][DEBUG][SimpleSubClient.cpp:120] OnlineClient::OnPlayerlogoff: 216838115 
05/13/26 22:52:00:591[3948][DEBUG][RobotRoomData.cpp:470] [ROBOT]__nUserID=111609512, nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:00:592[3948][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222634921(机器人), nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:00:592[3948][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759565(机器人), nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:00:724[11336][DEBUG][SimpleSubClient.cpp:110] OnlineClient::OnPlayerlogin: 241101107 
05/13/26 22:52:00:735[9956][DEBUG][PlayerData.cpp:115] OnQueryRobotMatchUserDataRet: 241101107 
05/13/26 22:52:00:741[11336][DEBUG][SimpleSubClient.cpp:110] OnlineClient::OnPlayerlogin: 241101107 
05/13/26 22:52:00:749[9956][DEBUG][PlayerData.cpp:115] OnQueryRobotMatchUserDataRet: 241101107 
05/13/26 22:52:00:776[11336][DEBUG][SimpleSubClient.cpp:120] OnlineClient::OnPlayerlogoff: 237310004 
05/13/26 22:52:00:974[9956][DEBUG][PlayerData.cpp:84] OnUpdateRobotMatchUserDataRet: 272309825 
05/13/26 22:52:01:598[3948][DEBUG][RobotRoomData.cpp:470] [ROBOT]__nUserID=111609512, nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:01:599[3948][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222634921(机器人), nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:01:599[3948][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759565(机器人), nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:02:175[11336][DEBUG][SimpleSubClient.cpp:120] OnlineClient::OnPlayerlogoff: 264392078 
05/13/26 22:52:02:605[3948][DEBUG][RobotRoomData.cpp:470] [ROBOT]__nUserID=111609512, nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:02:606[3948][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222634921(机器人), nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:02:606[3948][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759565(机器人), nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:02:637[6628][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759561(机器人), nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:02:637[6628][DEBUG][RobotRoomData.cpp:470] [ROBOT]__nUserID=111609512, nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:02:638[6628][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222634921(机器人), nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:02:638[6628][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759565(机器人), nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:02:639[6628][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759561(机器人), nFixTable=1, 虚拟桌号nTableNO=4001 
05/13/26 22:52:02:673[6628][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759538(机器人), nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:02:673[6628][DEBUG][RobotRoomData.cpp:470] [ROBOT]__nUserID=111609512, nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:02:674[6628][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222634921(机器人), nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:02:674[6628][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759565(机器人), nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:02:675[6628][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759561(机器人), nFixTable=1, 虚拟桌号nTableNO=4001 
05/13/26 22:52:02:675[6628][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759538(机器人), nFixTable=1, 虚拟桌号nTableNO=4001 
05/13/26 22:52:02:708[6628][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222634924(机器人), nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:02:709[6628][DEBUG][RobotRoomData.cpp:470] [ROBOT]__nUserID=111609512, nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:02:709[6628][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222634921(机器人), nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:02:710[6628][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759565(机器人), nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:02:710[6628][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759561(机器人), nFixTable=1, 虚拟桌号nTableNO=4001 
05/13/26 22:52:02:711[6628][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759538(机器人), nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:02:713[6628][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222634924(机器人), nFixTable=1, 虚拟桌号nTableNO=4001 
05/13/26 22:52:03:117[11336][DEBUG][SimpleSubClient.cpp:110] OnlineClient::OnPlayerlogin: 281753226 
05/13/26 22:52:03:126[9956][DEBUG][PlayerData.cpp:115] OnQueryRobotMatchUserDataRet: 281753226 
05/13/26 22:52:03:720[3948][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759561(机器人), nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:03:720[3948][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222634924(机器人), nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:03:987[11336][DEBUG][SimpleSubClient.cpp:120] OnlineClient::OnPlayerlogoff: 259787329 
05/13/26 22:52:04:093[11336][DEBUG][SimpleSubClient.cpp:110] OnlineClient::OnPlayerlogin: 281753226 
05/13/26 22:52:04:103[9956][DEBUG][PlayerData.cpp:115] OnQueryRobotMatchUserDataRet: 281753226 
05/13/26 22:52:04:456[11336][DEBUG][SimpleSubClient.cpp:120] OnlineClient::OnPlayerlogoff: 272548213 
05/13/26 22:52:04:486[11336][DEBUG][SimpleSubClient.cpp:110] OnlineClient::OnPlayerlogin: 281753226 
05/13/26 22:52:04:497[9956][DEBUG][PlayerData.cpp:115] OnQueryRobotMatchUserDataRet: 281753226 
05/13/26 22:52:04:503[11336][DEBUG][SimpleSubClient.cpp:110] OnlineClient::OnPlayerlogin: 281753226 
05/13/26 22:52:04:512[9956][DEBUG][PlayerData.cpp:115] OnQueryRobotMatchUserDataRet: 281753226 
05/13/26 22:52:04:726[3948][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759561(机器人), nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:04:726[3948][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222634924(机器人), nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:04:775[6628][DEBUG][RobotRoomData.cpp:470] [ROBOT]__nUserID=247093378, nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:05:731[3948][DEBUG][RobotRoomData.cpp:470] [ROBOT]__nUserID=247093378, nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:05:731[3948][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759561(机器人), nFixTable=1, 虚拟桌号nTableNO=4001 
05/13/26 22:52:05:732[3948][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222634924(机器人), nFixTable=1, 虚拟桌号nTableNO=4001 
05/13/26 22:52:06:738[3948][DEBUG][RobotRoomData.cpp:470] [ROBOT]__nUserID=247093378, nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:06:739[3948][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759561(机器人), nFixTable=1, 虚拟桌号nTableNO=4001 
05/13/26 22:52:06:739[3948][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222634924(机器人), nFixTable=1, 虚拟桌号nTableNO=4001 
05/13/26 22:52:07:429[11336][DEBUG][SimpleSubClient.cpp:120] OnlineClient::OnPlayerlogoff: 196366833 
05/13/26 22:52:07:460[11336][DEBUG][SimpleSubClient.cpp:120] OnlineClient::OnPlayerlogoff: 302342665 
05/13/26 22:52:07:515[5808][INFO][RoomDef.cpp:1306] ===========Clear User Sock ,be consult system, mapCount=0  
05/13/26 22:52:07:515[5808][INFO][RoomDef.cpp:1307] ===========Clear Client Block ,be consult system, mapCount=0  
05/13/26 22:52:07:747[3948][DEBUG][RobotRoomData.cpp:470] [ROBOT]__nUserID=247093378, nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:07:748[3948][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759561(机器人), nFixTable=1, 虚拟桌号nTableNO=4001 
05/13/26 22:52:07:748[3948][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222634924(机器人), nFixTable=1, 虚拟桌号nTableNO=4001 
05/13/26 22:52:08:755[3948][DEBUG][RobotRoomData.cpp:470] [ROBOT]__nUserID=247093378, nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:08:756[3948][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759561(机器人), nFixTable=1, 虚拟桌号nTableNO=4001 
05/13/26 22:52:08:756[3948][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222634924(机器人), nFixTable=1, 虚拟桌号nTableNO=4001 
05/13/26 22:52:09:543[11336][DEBUG][SimpleSubClient.cpp:110] OnlineClient::OnPlayerlogin: 280572562 
05/13/26 22:52:09:556[9956][DEBUG][PlayerData.cpp:115] OnQueryRobotMatchUserDataRet: 280572562 
05/13/26 22:52:09:761[3948][DEBUG][RobotRoomData.cpp:470] [ROBOT]__nUserID=247093378, nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:09:762[3948][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759561(机器人), nFixTable=1, 虚拟桌号nTableNO=4001 
05/13/26 22:52:09:762[3948][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222634924(机器人), nFixTable=1, 虚拟桌号nTableNO=4001 
05/13/26 22:52:10:079[11336][DEBUG][SimpleSubClient.cpp:110] OnlineClient::OnPlayerlogin: 280572562 
05/13/26 22:52:10:094[9956][DEBUG][PlayerData.cpp:115] OnQueryRobotMatchUserDataRet: 280572562 
05/13/26 22:52:10:492[11336][DEBUG][SimpleSubClient.cpp:110] OnlineClient::OnPlayerlogin: 280572562 
05/13/26 22:52:10:501[9956][DEBUG][PlayerData.cpp:115] OnQueryRobotMatchUserDataRet: 280572562 
05/13/26 22:52:10:767[3948][DEBUG][RobotRoomData.cpp:470] [ROBOT]__nUserID=247093378, nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:10:768[3948][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222759561(机器人), nFixTable=1, 虚拟桌号nTableNO=4000 
05/13/26 22:52:10:768[3948][DEBUG][RobotRoomData.cpp:464] [ROBOT]__nUserID=222634924(机器人), nFixTable=1, 虚拟桌号nTableNO=4001 
05/13/26 22:52:10:829[11336][DEBUG][SimpleSubClient.cpp:110] OnlineClient::OnPlayerlogin: 280572562 
05/13/26 22:52:10:838[9956][DEBUG][PlayerData.cpp:115] OnQueryRobotMatchUserDataRet: 280572562 
05/13/26 22:52:10:975[11336][DEBUG][SimpleSubClient.cpp:120] OnlineClient::OnPlayerlogoff: 244016587 
