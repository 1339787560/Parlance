local BaseGameDef = require("src.app.game.base.network.BaseGameDef")
local MJGameDef = require("src.app.game.mj.network.MJGameDef")
local MyGameDef = require("src.app.game.my.network.MyGameDef")

local MSG_TYPE = {
    RSP = 1,
    NOTIFY = 2,
    CUSTOM = 3
}

local CUSTOM_MSG_ID = {
    BETTERCARD = 1,
    GETREWARD = 2,
    LESSONOVER = 3,
    FIRSTHU = 4,
    CANHUTINGINFO = 5,
    NOTCALQYS = 6
}

local lessonData = {
    [1] = {
        {
            msgID = BaseGameDef.BASEGAME_GR_RESPONE_ENTER_GAME_OK,
            msgType = MSG_TYPE.RSP,
            dataFile = "RE_1SelfEnterGame1",
            datatbl = {
                ei = {
                    dwUserStatus = {
                        65,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                    },
                    nBaseDeposit = 0,
                    nBaseScore   = 0,
                    nBout        = 0,
                    nKickOffTime = 120,
                    nRoomID      = 13162,
                    nTableNO     = 0,
                    nTotalChair  = 4,
                },
                nFixBaseSilver = 2000,
                nResultDiff = {
                    {
                        nItem = {
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                        }
                    },
                    {
                        nItem = {
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                        }
                    },
                    {
                        nItem = {
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                        }
                    },
                    {
                        nItem = {
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                        }
                    },
                    {
                        nItem = {
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                        }
                    },
                    {
                        nItem = {
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                        }
                    },
                    {
                        nItem = {
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                        }
                    },
                    {
                        nItem = {
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                        }
                    }
                },
                nTotalResult = {
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                },
                soloplaerhead = {
                    dwUserStatus = {
                        65,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                    },
                    nPlayerCount = 1,
                    nRoomID      = 13162,
                    nTableNO     = 0,
                },
                soloplayer = {
                    {
                        bRefuse      = 0,
                        nBout        = 510,
                        nBreakOff    = 0,
                        nChairNO     = 0,
                        nClothingID  = 0,
                        nDeposit     = 100000,
                        nLoss        = 292,
                        nNetSpeed    = 0,
                        nNickSex     = 0,
                        nPlayerLevel = 100000,
                        nPortrait    = 0,
                        nScore       = 823138,
                        nStandOff    = 3,
                        nStatus      = 0,
                        nTableNO     = 0,
                        nTimeCost    = 240,
                        nUserID      = 733811,
                        nUserType    = 2048,
                        nWin         = 215,
                        szNickName   = "",
                        szUsername   = "wuchen0002",
                    }
                }
            }
        },
        {
            msgID = MyGameDef.MY_GR_GET_MAX_FAN,
            msgType = MSG_TYPE.RSP,
            dataFile = "RE_2rspGetMaxFan1",
            datatbl = {
                nRoomID = 13162,
                nReserved = {
                    0,0,0,0
                },
                nMaxFan = 32
            }
        },
        {
            msgID = BaseGameDef.BASEGAME_GR_PLAYER_ENTER,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_3EnterGame1",
            datatbl = {
                bRefuse      = 0,
                nBout        = 99,
                nBreakOff    = 0,
                nChairNO     = 1,
                nClothingID  = 0,
                nDeposit     = 0,
                nLoss        = 78,
                nNetSpeed    = 0,
                nNickSex     = 0,
                nPlayerLevel = 80000,
                nPortrait    = 0,
                nReserved = {
                    0,
                    0,
                    0,
                },
                nScore       = -36443,
                nStandOff    = 0,
                nStatus      = 0,
                nTableNO     = 0,
                nTimeCost    = 300,
                nUserID      = 733813,
                nUserType    = 2048,
                nWin         = 20,
                szNickName   = "",
                szUsername   = "wuchen0004",
            }
        },
        {
            msgID = BaseGameDef.BASEGAME_GR_PLAYER_ENTER,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_4EnterGame2",
            datatbl = {
                bRefuse      = 0,
                nBout        = 105,
                nBreakOff    = 0,
                nChairNO     = 2,
                nClothingID  = 0,
                nDeposit     = 0,
                nLoss        = 81,
                nNetSpeed    = 0,
                nNickSex     = 0,
                nPlayerLevel = 30000,
                nPortrait    = 0,
                nReserved = {
                    0,
                    0,
                    0,
                },
                nScore       = -163084,
                nStandOff    = 0,
                nStatus      = 0,
                nTableNO     = 0,
                nTimeCost    = 540,
                nUserID      = 733812,
                nUserType    = 2048,
                nWin         = 24,
                szNickName   = "",
                szUsername   = "wuchen0003",
            }
        },
        {
            msgID = BaseGameDef.BASEGAME_GR_PLAYER_ENTER,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_5EnterGame3",
            datatbl = {
                bRefuse      = 0,
                nBout        = 89,
                nBreakOff    = 0,
                nChairNO     = 3,
                nClothingID  = 0,
                nDeposit     = 0,
                nLoss        = 65,
                nNetSpeed    = 0,
                nNickSex     = 0,
                nPlayerLevel = 80000,
                nPortrait    = 0,
                nReserved = {
                    0,
                    0,
                    0,
                },
                nScore       = 159194,
                nStandOff    = 1,
                nStatus      = 0,
                nTableNO     = 0,
                nTimeCost    = 300,
                nUserID      = 733810,
                nUserType    = 2048,
                nWin         = 23,
                szNickName   = "",
                szUsername   = "wuchen0001",
            }
        },
    },
    [MSG_TYPE.NOTIFY] = {
        {
            msgID = BaseGameDef.BASEGAME_GR_START_SOLOTABLE,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_6StartGame1",
            datatbl = {
                StartData = {
                    bAllowChi      = 0,
                    bAnGangShow    = 1,
                    bBaibanNoSort  = 1,
                    bForbidDesert  = 0,
                    bJokerSortIn   = 0,
                    bNeedDeposit   = 1,
                    bQuickCatch    = 0,
                    dwCurrentFlags = 0,
                    dwStatus       = 5,
                    nBanker        = 0,
                    nBankerHold    = 1,
                    nBaseDeposit   = 2000,
                    nBaseScore     = 1,
                    nBeginNO       = 0,
                    nBoutCount     = 1,
                    nCurrentCatch  = 53,
                    nCurrentChair  = 0,
                    nDices = {
                        2,
                        3,
                        0,
                        0,
                    },
                    nEntrustWait   = 2,
                    nFanID         = -1,
                    nFirstCatch    = 0,
                    nFirstThrow    = 0,
                    nHuGains       = 0,
                    nJokerID       = 108,
                    nJokerID2      = -1,
                    nJokerNO       = -1,
                    nMaxAutoThrow  = 2147483647,
                    nPGCHWait      = 30,
                    nPGCHWaitEx    = 2,
                    nTailTaken     = 0,
                    nThrowWait     = 99,
                    nTotalCards    = 114,
                    szSerialNO = {
                        "05b47ed47ec9e5499bdd003463e453"
                    }
                },
                nCardsCount = {
                    14,
                    13,
                    13,
                    13,
                },
                nChairCards = {
                    18,
                    19,
                    11,
                    31,
                    22,
                    14,
                    5,
                    16,
                    35,
                    63,
                    37,
                    51,
                    86,
                    112,
                    -1,
                    -1,
                    -1,
                    -1,
                    -1,
                    -1,
                    -1,
                    -1,
                    -1,
                    -1,
                    -1,
                    -1,
                    -1,
                    -1,
                    -1,
                    -1,
                    -1,
                    -1,
                },
                nDingQueWait = 99,
                nGiveupWait  = 30,
                nShowTask    = 0,
                soloPlayers = {
                    {
                        bRefuse      = 0,
                        nBout        = 510,
                        nBreakOff    = 0,
                        nChairNO     = 0,
                        nClothingID  = 0,
                        nDeposit     = 100000,
                        nLoss        = 292,
                        nNetSpeed    = 0,
                        nNickSex     = 0,
                        nPlayerLevel = 100000,
                        nPortrait    = 0,
                        nScore       = 823138,
                        nStandOff    = 3,
                        nStatus      = 14,
                        nTableNO     = 1,
                        nTimeCost    = 290,
                        nUserID      = 733811,
                        nUserType    = 2048,
                        nWin         = 215,
                        szNickName   = "wuchen0002",
                        szUsername   = "wuchen0002",
                    },
                    {
                        bRefuse      = 0,
                        nBout        = 99,
                        nBreakOff    = 0,
                        nChairNO     = 1,
                        nClothingID  = 0,
                        nDeposit     = 80000,
                        nLoss        = 79,
                        nNetSpeed    = 0,
                        nNickSex     = 0,
                        nPlayerLevel = 80000,
                        nPortrait    = 0,
                        nScore       = -36443,
                        nStandOff    = 0,
                        nStatus      = 14,
                        nTableNO     = 1,
                        nTimeCost    = 332,
                        nUserID      = 733813,
                        nUserType    = 2048,
                        nWin         = 20,
                        szNickName   = "wuchen0004",
                        szUsername   = "wuchen0004",
                    },
                    {
                        bRefuse      = 0,
                        nBout        = 105,
                        nBreakOff    = 0,
                        nChairNO     = 2,
                        nClothingID  = 0,
                        nDeposit     = 30000,
                        nLoss        = 81,
                        nNetSpeed    = 0,
                        nNickSex     = 0,
                        nPlayerLevel = 30000,
                        nPortrait    = 0,
                        nScore       = -163084,
                        nStandOff    = 0,
                        nStatus      = 14,
                        nTableNO     = 1,
                        nTimeCost    = 573,
                        nUserID      = 733812,
                        nUserType    = 2048,
                        nWin         = 24,
                        szNickName   = "wuchen0003",
                        szUsername   = "wuchen0003",
                    },
                    {
                        bRefuse      = 0,
                        nBout        = 89,
                        nBreakOff    = 0,
                        nChairNO     = 3,
                        nClothingID  = 0,
                        nDeposit     = 80000,
                        nLoss        = 65,
                        nNetSpeed    = 0,
                        nNickSex     = 0,
                        nPlayerLevel = 80000,
                        nPortrait    = 0,
                        nScore       = 159194,
                        nStandOff    = 1,
                        nStatus      = 14,
                        nTableNO     = 1,
                        nTimeCost    = 332,
                        nUserID      = 733810,
                        nUserType    = 2048,
                        nWin         = 23,
                        szNickName   = "wuchen0001",
                        szUsername   = "wuchen0001",
                    },
                },
                soloTable = {
                    nRoomID    = 13162,
                    nTableNO   = 1,
                    nUserCount = 4,
                    nUserIDs = {
                        733811,
                        733813,
                        733812,
                        733810,
                        0,
                        0,
                        0,
                        0,
                    }
                },
                szSerialNO   = "05b47ed47ec9e5499bdd003463e453"
            }
        },
        {
            msgID = MyGameDef.MY_GR_PRE_SAVE_RESULT,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_7PreSaveResult1",
            datatbl = {
                hupoints = {
                    0,
                    0,
                    0,
                    0,
                },
                nChairNO    = -1,
                nDepositDiffs = {
                    -10000,
                    -10000,
                    -10000,
                    -10000,
                },
                nFlag        = 6,
                nHuStatus = {
                    {
                        nItem = {
                            0,
                            0,
                            0,
                        }
                    },
                    {
                        nItem = {
                            0,
                            0,
                            0,
                        }
                    },
                    {
                        nItem = {
                            0,
                            0,
                            0,
                        }
                    },
                    {
                        nItem = {
                            0,
                            0,
                            0,
                        }
                    }
                },
                nOldDeposits = {
                    100000,
                    80000,
                    30000,
                    80000,
                },
                nOldScores = {
                    0,
                    0,
                    0,
                    0,
                },
                nScoreDiffs = {
                    0,
                    0,
                    0,
                    0,
                }
            }
        },
    },
    [3] = {
        {
            msgID = MyGameDef.MY_GR_SYSTEMMSG,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_8NtfMsg1",
            datatbl = {
                nFangCardChairNO = 13,
                nRoomID = 0,
                nChairNO = 1,
                nMsgID = 8,
                nMJID = 60,
                nEventID = 25,
                nUserID = 0,
            }
        },
        {
            msgID = MyGameDef.MY_GR_SYSTEMMSG,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_9NtfMsg2",
            datatbl = {
                nChairNO         = 2,
                nEventID         = 17,
                nFangCardChairNO = 7,
                nMJID            = 99,
                nMsgID           = 8,
                nRoomID          = 0,
                nUserID          = 0,
            }
        },
        {
            msgID = MyGameDef.MY_GR_SYSTEMMSG,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_10NtfMsg3",
            datatbl = {
                nChairNO         = 3,
                nEventID         = 34,
                nFangCardChairNO = 4,
                nMJID            = 97,
                nMsgID           = 8,
                nRoomID          = 0,
                nUserID          = 0,
            }
        },
    },
    [4] = {
        {
            msgID = MyGameDef.MY_GR_EXCHANGE_CARDS,
            msgType = MSG_TYPE.RSP,
            dataFile = "RE_11rspExChangeCards1",
            datatbl = {}
        },
        {
            msgID = MyGameDef.MY_GR_SYSTEMMSG,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_12NtfMsg4",
            datatbl = {
                nChairNO         = 0,
                nEventID         = 37,
                nFangCardChairNO = 63,
                nMJID            = 86,
                nMsgID           = 8,
                nRoomID          = 0,
                nUserID          = 0,
            }
        },
        {
            msgID = MyGameDef.MY_GR_EXCHANGE3CARDS_FINISHED,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_13Exchange3CardsFinished1",
            datatbl = {
                nChairNO             = 0,
                nExchange3Cards = {
                    {
                        97,
                        34,
                        4,
                    },
                    {
                        86,
                        37,
                        63,
                    },
                    {
                        60,
                        25,
                        13,
                    },
                    {
                        99,
                        17,
                        7,
                    },
                },
                nExchange3CardsCount = 3,
                nExchangeDirection   = 0,
                nReserved = {
                    0,
                    0,
                    0,
                    0,
                },
                nRoomID              = 13162,
                nSendChair           = 0,
                nSendTable           = 0,
                nSendUser            = 733811,
                nTableNO             = 1,
                nUserID              = 733811,
            }
        },
    },
    [5] = {
        {
            msgID = MyGameDef.MY_GR_SYSTEMMSG,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_14NtfMsg5",
            datatbl = {
                nChairNO         = 1,
                nEventID         = 0,
                nFangCardChairNO = 0,
                nMJID            = 0,
                nMsgID           = 7,
                nRoomID          = 0,
                nUserID          = 0,
            }
        },
        {
            msgID = MyGameDef.MY_GR_SYSTEMMSG,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_15NtfMsg6",
            datatbl = {
                nChairNO         = 2,
                nEventID         = 0,
                nFangCardChairNO = 0,
                nMJID            = 0,
                nMsgID           = 7,
                nRoomID          = 0,
                nUserID          = 0,
            }
        },
        {
            msgID = MyGameDef.MY_GR_SYSTEMMSG,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_16NtfMsg7",
            datatbl = {
                nChairNO         = 3,
                nEventID         = 0,
                nFangCardChairNO = 0,
                nMJID            = 0,
                nMsgID           = 7,
                nRoomID          = 0,
                nUserID          = 0,
            }
        },
    },
    [6] = {
        {
            msgID = MyGameDef.MY_GR_SYSTEMMSG,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_17NtfMsg8",
            datatbl = {
                nChairNO         = 0,
                nEventID         = 1,
                nFangCardChairNO = 0,
                nMJID            = 0,
                nMsgID           = 7,
                nRoomID          = 0,
                nUserID          = 0,
            }
        },
        {
            msgID = MyGameDef.MY_GR_AUCTION_FINISHED,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_18FixMissFinished1",
            datatbl = {
                bAuto            = 0,
                dPGCH = {
                    0,
                    0,
                    0,
                    0,
                },
                nBankerHuFan     = 0,
                nChairNO         = 0,
                nDingQueCardType = {
                    1,
                    0,
                    0,
                    0,
                },
                nReserved = {
                    0,
                    0,
                    0,
                },
                nRoomID          = 13162,
                nTableNO         = 1,
                nUserID          = 733811,
            }
        },
        {
            msgID = MJGameDef.MJ_QUERY_TINGINFO,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_19ntfPBTingInfo1",
            datatbl = {
                tingitems = {
                    {
                        throwidx = 1
                    },
                    {
                        throwidx = 2
                    },
                    {
                        throwidx = 3
                    },
                    {
                        throwidx = 5
                    },
                    {
                        throwidx = 6
                    },
                    {
                        throwidx = 8
                    },
                    {
                        throwidx = 9
                    },
                    {
                        throwidx = 17
                    },
                    {
                        throwidx = 28
                    },
                    {
                        throwidx = 35
                    }
                }
            }
        },
    },
    [7] = {
        {
            msgID = MJGameDef.MJ_GR_THROW_CARDS,
            msgType = MSG_TYPE.RSP,
            dataFile = "RE_20rspThrowCard1",
            delay = 1,
            datatbl = {
                bNextFirst = 1,
                nNextChair = 3
            }
        },
        {
            msgID = MJGameDef.MJ_QUERY_HUINFO,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_21ntfPBHuInfo1",
            datatbl = nil
        },
        {
            msgID = MJGameDef.MJ_GR_CARD_CAUGHT,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_22ntfCardCaught1",
            delay = 1,
            datatbl = {
                dwFlags   = 0,
                nCardID   = -1,
                nCardNO   = 53,
                nChairNO  = 3,
                nReserved = {
                    0,
                    0,
                    0,
                    0,
                }
            }
        },
        {
            msgID = MJGameDef.MJ_GR_CARDS_THROW,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_23ntfCardsThrow1",
            delay = 1,
            datatbl = {
                bNextFirst  = 1,
                bNextPass   = 0,
                dwCardsType = 1,
                dwFlags = {
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                },
                nCardIDs = {
                    17
                },
                nCardsCount = 1,
                nChairNO    = 3,
                nNextChair  = 2,
                nRemains    = 13,
                nReserved = {
                    0,
                    0,
                    0,
                    0,
                },
                nThrowCount = 0,
                nUserID     = 733810,
            }
        },
        {
            msgID = MJGameDef.MJ_GR_CARD_CAUGHT,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_24ntfCardCaught2",
            delay = 1,
            datatbl = {
                dwFlags   = 0,
                nCardID   = -1,
                nCardNO   = 54,
                nChairNO  = 2,
                nReserved = {
                    0,
                    0,
                    0,
                    0,
                }
            }
        },
        {
            msgID = MJGameDef.MJ_GR_CARDS_THROW,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_25ntfCardsThrow2",
            delay = 1,
            datatbl = {
                bNextFirst  = 1,
                bNextPass   = 0,
                dwCardsType = 1,
                dwFlags = {
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                },
                nCardIDs = {
                    88
                },
                nCardsCount = 1,
                nChairNO    = 2,
                nNextChair  = 1,
                nRemains    = 13,
                nReserved = {
                    0,
                    0,
                    0,
                    0,
                },
                nThrowCount = 0,
                nUserID     = 733812,
            }
        },
        {
            msgID = MJGameDef.MJ_GR_CARD_CAUGHT,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_26ntfCardCaught3",
            delay = 1,
            datatbl = {
                dwFlags   = 0,
                nCardID   = -1,
                nCardNO   = 55,
                nChairNO  = 1,
                nReserved = {
                    0,
                    0,
                    0,
                    0,
                }
            }
        },
        {
            msgID = MJGameDef.MJ_GR_CARDS_THROW,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_27ntfCardsThrow3",
            delay = 1,
            datatbl = {
                bNextFirst  = 1,
                bNextPass   = 0,
                dwCardsType = 1,
                dwFlags = {
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                },
                nCardIDs = {
                    89,
                },
                nCardsCount = 1,
                nChairNO    = 1,
                nNextChair  = 0,
                nRemains    = 13,
                nReserved = {
                    0,
                    0,
                    0,
                    0,
                },
                nThrowCount = 0,
                nUserID     = 733813,
            }
        },
        {
            msgID = MJGameDef.MJ_GR_CARD_CAUGHT,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_28ntfCardCaught4",
            datatbl = {
                dwFlags   = 0,
                nCardID   = 23,
                nCardNO   = 56,
                nChairNO  = 0,
                nReserved = {
                    0,
                    0,
                    0,
                    0,
                },
            }
        },
    },
    [8] = {
        {
            msgID = CUSTOM_MSG_ID.NOTCALQYS,
            msgType = MSG_TYPE.CUSTOM,
        },
        {
            msgID = MJGameDef.MJ_QUERY_TINGINFO,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_29ntfPBTingInfo2",
            datatbl = {
                tingitems = {
                    {
                        throwidx = 1
                    },
                    {
                        throwidx = 2
                    },
                    {
                        throwidx = 3
                    },
                    {
                        throwidx = 5
                    },
                    {
                        throwidx = 6
                    },
                    {
                        huitems = {
                            {
                                fan      = 4,
                                hucardix = 7,
                                huflags = {
                                    39
                                }
                            },
                            {
                                fan      = 4,
                                hucardix = 28,
                                huflags = {
                                    39
                                }
                            },
                            {
                                fan      = 4,
                                hucardix = 35,
                                huflags = {
                                    39
                                }
                            }
                        },
                        throwidx = 8,
                    },
                    {
                        huitems = {
                            {
                                fan      = 12,
                                hucardix = 8,
                                huflags = {
                                    32
                                }
                            },
                            {
                                fan      = 4,
                                hucardix = 26,
                                huflags = {
                                    39
                                }
                            },
                            {
                                fan      = 4,
                                hucardix = 27,
                                huflags = {
                                    39
                                }
                            },
                            {
                                fan      = 12,
                                hucardix = 28,
                                huflags = {
                                    32
                                }
                            },
                            {
                                fan      = 4,
                                hucardix = 29,
                                huflags = {
                                    39
                                }
                            },
                            {
                                fan      = 12,
                                hucardix = 35,
                                huflags = {
                                    32
                                }
                            }
                        },
                        throwidx = 9,
                    },
                    {
                        huitems = {
                            {
                                fan      = 32,
                                hucardix = 7,
                                huflags = {
                                    3,
                                    36,
                                    41,
                                }
                            },
                            {
                                fan      = 32,
                                hucardix = 8,
                                huflags = {
                                    3,
                                    32,
                                }
                            },
                            {
                                fan      = 32,
                                hucardix = 9,
                                huflags = {
                                    3,
                                    32,
                                }
                            },
                            {
                                fan      = 32,
                                hucardix = 35,
                                huflags = {
                                    3,
                                    32,
                                }
                            },
                        },
                        throwidx = 28,
                    },
                    {
                        throwidx = 35,
                    },
                }
            }
        },
        {
            msgID = CUSTOM_MSG_ID.BETTERCARD,
            msgType = MSG_TYPE.CUSTOM,
        },
    },
    [9] = {
        {
            msgID = MJGameDef.MJ_GR_THROW_CARDS,
            msgType = MSG_TYPE.RSP,
            dataFile = "RE_30rspThrowCard2",
            datatbl = {
                bNextFirst = 1,
                nNextChair = 3,
            }
        },
        {
            msgID = MJGameDef.MJ_QUERY_HUINFO,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_31ntfPBHuInfo2",
            delay = 1,
            datatbl = {
                huitems = {
                    {
                        fan      = 32,
                        hucardix = 7,
                    },
                    {
                        fan      = 32,
                        hucardix = 8,
                    },
                    {
                        fan      = 32,
                        hucardix = 9,
                    },
                    {
                        fan      = 32,
                        hucardix = 35,
                    }
                }
            }
        },
        {
            msgID = MJGameDef.MJ_GR_CARD_CAUGHT,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_32ntfCardCaught5",
            delay = 1,
            datatbl = {
                dwFlags   = 0,
                nCardID   = -1,
                nCardNO   = 57,
                nChairNO  = 3,
                nReserved = {
                    0,
                    0,
                    0,
                    0,
                }
            }
        },
        {
            msgID = MJGameDef.MJ_GR_CARDS_THROW,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_33ntfCardsThrow4",
            delay = 1,
            datatbl = {
                bNextFirst  = 1,
                bNextPass   = 0,
                dwCardsType = 1,
                dwFlags = {
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                },
                nCardIDs = {
                    98
                },
                nCardsCount = 1,
                nChairNO    = 3,
                nNextChair  = 2,
                nRemains    = 13,
                nReserved = {
                    0,
                    0,
                    0,
                    0,
                },
                nThrowCount = 0,
                nUserID     = 733810,
            }
        },
        {
            msgID = MJGameDef.MJ_GR_CARD_CAUGHT,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_34ntfCardCaught6",
            delay = 1,
            datatbl = {
                dwFlags   = 0,
                nCardID   = -1,
                nCardNO   = 58,
                nChairNO  = 2,
                nReserved = {
                    0,
                    0,
                    0,
                    0,
                }
            }
        },
        {
            msgID = MJGameDef.MJ_GR_CARDS_THROW,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_35ntfCardsThrow5",
            delay = 1,
            datatbl = {
                bNextFirst  = 1,
                bNextPass   = 0,
                dwCardsType = 1,
                dwFlags = {
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                },
                nCardIDs = {
                    80
                },
                nCardsCount = 1,
                nChairNO    = 2,
                nNextChair  = 1,
                nRemains    = 13,
                nReserved = {
                    0,
                    0,
                    0,
                    0,
                },
                nThrowCount = 0,
                nUserID     = 733812,
            }
        },
        {
            msgID = MJGameDef.MJ_GR_CARD_CAUGHT,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_36ntfCardCaught7",
            delay = 1,
            datatbl = {
                dwFlags   = 0,
                nCardID   = -1,
                nCardNO   = 59,
                nChairNO  = 1,
                nReserved = {
                    0,
                    0,
                    0,
                    0,
                }
            }
        },
        {
            msgID = MJGameDef.MJ_GR_CARDS_THROW,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_37ntfCardsThrow6",
            delay = 1,
            datatbl = {
                bNextFirst  = 1,
                bNextPass   = 0,
                dwCardsType = 1,
                dwFlags = {
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                },
                nCardIDs = {
                    41
                },
                nCardsCount = 1,
                nChairNO    = 1,
                nNextChair  = 0,
                nRemains    = 13,
                nReserved = {
                    0,
                    0,
                    0,
                    0,
                },
                nThrowCount = 0,
                nUserID     = 733813,
            }
        },
        {
            msgID = MJGameDef.MJ_GR_CARD_CAUGHT,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_38ntfCardCaught8",
            datatbl = {
                dwFlags   = 8,
                nCardID   = 24,
                nCardNO   = 60,
                nChairNO  = 0,
                nReserved = {
                    0,
                    0,
                    0,
                    0,
                }
            }
        },
    },
    [10] = {
        {
            msgID = MJGameDef.MJ_QUERY_TINGINFO,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_39ntfPBTingInfo3",
            datatbl = {
                tingitems = {
                    {
                        huitems = {
                            {
                                fan      = 24,
                                hucardix = 1,
                                huflags = {
                                    3,
                                    36,
                                }
                            },
                            {
                                fan      = 24,
                                hucardix = 4,
                                huflags = {
                                    3,
                                }
                            },
                            {
                                fan      = 32,
                                hucardix = 7,
                                huflags = {
                                    3,
                                    36,
                                    41,
                                }
                            },
                            {
                                fan      = 24,
                                hucardix = 8,
                                huflags = {
                                    3,
                                    39,
                                }
                            },
                            {
                                fan      = 32,
                                hucardix = 35,
                                huflags = {
                                    3,
                                    36,
                                    42,
                                }
                            },
                        },
                        throwidx = 1
                    },
                    {
                        huitems = {
                            {
                                fan      = 32,
                                hucardix = 2,
                                huflags = {
                                    3,
                                    36,
                                    41,
                                }
                            },
                            {
                                fan      = 32,
                                hucardix = 7,
                                huflags = {
                                    3,
                                    36,
                                    41,
                                }
                            },
                            {
                                fan      = 24,
                                hucardix = 8,
                                huflags = {
                                    3,
                                    39,
                                }
                            },
                            {
                                fan      = 32,
                                hucardix = 35,
                                huflags = {
                                    3,
                                    36,
                                    41,
                                }
                            },
                        },
                        throwidx = 2
                    },
                    {
                        huitems = {
                            {
                                fan      = 32,
                                hucardix = 3,
                                huflags = {
                                    3,
                                    36,
                                    42,
                                }
                            },
                            {
                                fan      = 32,
                                hucardix = 7,
                                huflags = {
                                    3,
                                    36,
                                    41,
                                }
                            },
                            {
                                fan      = 24,
                                hucardix = 8,
                                huflags = {
                                    3,
                                    39,
                                }
                            },
                            {
                                fan      = 32,
                                hucardix = 35,
                                huflags = {
                                    3,
                                    36,
                                    42,
                                }
                            }
                        },
                        throwidx = 3
                    },
                    {
                        huitems = {
                            {
                                fan      = 24,
                                hucardix = 5,
                                huflags = {
                                    3,
                                    36,
                                }
                            },
                            {
                                fan      = 24,
                                hucardix = 6,
                                huflags = {
                                    3,
                                    36,
                                }
                            },
                            {
                                fan      = 32,
                                hucardix = 7,
                                huflags = {
                                    3,
                                    36,
                                    42,
                                }
                            },
                            {
                                fan      = 24,
                                hucardix = 8,
                                huflags = {
                                    3,
                                    39,
                                }
                            },
                            {
                                fan      = 24,
                                hucardix = 9,
                                huflags = {
                                    3,
                                    36,
                                }
                            },
                            {
                                fan      = 32,
                                hucardix = 35,
                                huflags = {
                                    3,
                                    36,
                                    42,
                                }
                            },
                        },
                        throwidx = 5
                    },
                    {
                        huitems = {
                            {
                                fan      = 32,
                                hucardix = 4,
                                huflags = {
                                    3,
                                    33,
                                }
                            },
                            {
                                fan      = 24,
                                hucardix = 6,
                                huflags = {
                                    3,
                                    36,
                                }
                            },
                            {
                                fan      = 32,
                                hucardix = 7,
                                huflags = {
                                    3,
                                    36,
                                    41,
                                }
                            },
                            {
                                fan      = 24,
                                hucardix = 8,
                                huflags = {
                                    3,
                                    39,
                                }
                            },
                            {
                                fan      = 24,
                                hucardix = 9,
                                huflags = {
                                    3,
                                    36,
                                }
                            },
                            {
                                fan      = 32,
                                hucardix = 35,
                                huflags = {
                                    3,
                                    36,
                                    42,
                                }
                            },
                        },
                        throwidx = 6
                    },
                    {
                        huitems = {
                            {
                                fan      = 32,
                                hucardix = 7,
                                huflags = {
                                    3,
                                    36,
                                    41,
                                }
                            },
                            {
                                fan      = 32,
                                hucardix = 8,
                                huflags = {
                                    3,
                                    32,
                                }
                            },
                            {
                                fan      = 32,
                                hucardix = 9,
                                huflags = {
                                    3,
                                    32,
                                }
                            },
                            {
                                fan      = 32,
                                hucardix = 35,
                                huflags = {
                                    3,
                                    32,
                                }
                            }
                        },
                        throwidx = 7
                    },
                    {
                        huitems = {
                            {
                                fan      = 24,
                                hucardix = 1,
                                huflags = {
                                    3,
                                    39,
                                }
                            },
                            {
                                fan      = 24,
                                hucardix = 2,
                                huflags = {
                                    3,
                                    39,
                                }
                            },
                            {
                                fan      = 32,
                                hucardix = 3,
                                huflags = {
                                    3,
                                    36,
                                    42,
                                }
                            },
                            {
                                fan      = 32,
                                hucardix = 4,
                                huflags = {
                                    3,
                                    33,
                                }
                            },
                            {
                                fan      = 32,
                                hucardix = 5,
                                huflags = {
                                    3,
                                    33,
                                    41,
                                }
                            },
                            {
                                fan      = 32,
                                hucardix = 6,
                                huflags = {
                                    3,
                                    36,
                                    41,
                                }
                            },
                            {
                                fan      = 32,
                                hucardix = 7,
                                huflags = {
                                    3,
                                    36,
                                    41,
                                }
                            },
                            {
                                fan      = 32,
                                hucardix = 8,
                                huflags = {
                                    3,
                                    36,
                                    41,
                                }
                            },
                            {
                                fan      = 24,
                                hucardix = 9,
                                huflags = {
                                    3,
                                    39,
                                }
                            },
                            {
                                fan      = 32,
                                hucardix = 35,
                                huflags = {
                                    3,
                                    36,
                                    42,
                                }
                            },
                        },
                        throwidx = 8
                    },
                    {
                        huitems = {
                            {
                                fan      = 12,
                                hucardix = 4,
                                huflags = {
                                    3,
                                }
                            },
                            {
                                fan      = 24,
                                hucardix = 5,
                                huflags = {
                                    3,
                                    39,
                                }
                            },
                            {
                                fan      = 24,
                                hucardix = 6,
                                huflags = {
                                    3,
                                    39,
                                }
                            },
                            {
                                fan      = 32,
                                hucardix = 7,
                                huflags = {
                                    3,
                                    32,
                                }
                            },
                            {
                                fan      = 32,
                                hucardix = 8,
                                huflags = {
                                    3,
                                    32,
                                }
                            },
                            {
                                fan      = 24,
                                hucardix = 9,
                                huflags = {
                                    3,
                                    36,
                                }
                            },
                            {
                                fan      = 32,
                                hucardix = 35,
                                huflags = {
                                    3,
                                    29,
                                    32,
                                }
                            },
                        },
                        throwidx = 9
                    },
                    {
                        huitems = {
                            {
                                fan      = 32,
                                hucardix = 7,
                                huflags = {
                                    3,
                                    36,
                                    41,
                                }
                            },
                            {
                                fan      = 24,
                                hucardix = 8,
                                huflags = {
                                    3,
                                    39,
                                }
                            },
                            {
                                fan      = 32,
                                hucardix = 35,
                                huflags = {
                                    3,
                                    36,
                                    42,
                                }
                            },
                        },
                        throwidx = 35
                    },
                }
            }
        },
        {
            msgID = CUSTOM_MSG_ID.CANHUTINGINFO,
            msgType = MSG_TYPE.CUSTOM,
        },
    },
    [11] = {
        {
            msgID = MJGameDef.MJ_GR_HU_CARD,
            msgType = MSG_TYPE.RSP,
            dataFile = "RE_40rspHuCard1",
            datatbl = {
            }
        },
        {
            msgID = CUSTOM_MSG_ID.FIRSTHU,
            msgType = MSG_TYPE.CUSTOM,
        },
        {
            msgID = MyGameDef.MY_GR_SYSTEMMSG,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_41NtfMsg9",
            datatbl = {
                nChairNO         = 0,
                nEventID         = 2,
                nFangCardChairNO = 0,
                nMJID            = 24,
                nMsgID           = 3,
                nRoomID          = 0,
                nUserID          = 0,
            }
        },
        {
            msgID = MyGameDef.MY_GR_PRE_SAVE_RESULT,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_42PreSaveResult2",
            datatbl = {
                huitemhead = {
                    nChairNO           = 0,
                    nCount             = 1,
                    nPreSaveAllDeposit = 148000,
                },
                huiteminfo = {
                    {
                        bSend        = 1,
                        bWin         = 1,
                        nHuDeposits  = 148000,
                        nHuFan       = 32,
                        nHuFlag      = 2,
                        nHuGains = {
                            0,
                            0,
                            0,
                            6,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            4,
                            2,
                            0,
                            0,
                            0,
                            0,
                            2,
                            0,
                            0,
                            0,
                        },
                        nHuID        = 24,
                        nRelateChair = {
                            -1,
                            1,
                            2,
                            3,
                        }
                    }
                },
                hupoints = {
                    96,
                    -32,
                    -32,
                    -32,
                },
                nChairNO           = 0,
                nDepositDiffs = {
                    148000,
                    -64000,
                    -20000,
                    -64000,
                },
                nFlag              = 4,
                nHuStatus = {
                    {
                        nItem = {
                            8194,
                            0,
                            73400320,
                        }
                    },
                    {
                        nItem = {
                            0,
                            0,
                            0,
                        }
                    },
                    {
                        nItem = {
                            0,
                            0,
                            0,
                        }
                    },
                    {
                        nItem = {
                            0,
                            0,
                            0,
                        }
                    },
                },
                nOldDeposits = {
                    90000,
                    70000,
                    20000,
                    70000,
                },
                nOldScores = {
                    823138,
                    -36443,
                    -163084,
                    159194,
                },
                nPreSaveAllDeposit = 148000,
                nScoreDiffs = {
                    96,
                    -32,
                    -32,
                    -32,
                },
            }
        },
    },
    [12] = {
        {
            msgID = MyGameDef.MY_GR_PLAYING_DEPOSIT_NOT_ENOUGH,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_43ntfPlayerDepositNotEnough1",
            delay = 1,
            datatbl = {
                nGiveUpChair = {
                    -1,
                    -1,
                    2,
                    -1,
                },
                nLastSecond  = 30,
                nNeedDeposit = 30000,
            }
        },
        {
            msgID = MyGameDef.MY_GR_SYSTEMMSG,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_44NtfMsg10",
            datatbl = {
                nChairNO         = 2,
                nEventID         = 64,
                nFangCardChairNO = 0,
                nMJID            = 0,
                nMsgID           = 5,
                nRoomID          = 0,
                nUserID          = 0,
            }
        },
        {
            msgID = MyGameDef.MY_GR_PRE_SAVE_RESULT,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_45PreSaveResult3",
            datatbl = {
                hupoints = {
                    0,
                    0,
                    0,
                    0,
                },
                nChairNO           = 2,
                nDepositDiffs = {
                    0,
                    0,
                    0,
                    0,
                },
                nFlag              = 5,
                nHuStatus = {
                    {
                        nItem = {
                            8194,
                            0,
                            73400320,
                        }
                    },
                    {
                        nItem = {
                            0,
                            0,
                            0,
                        }
                    },
                    {
                        nItem = {
                            64,
                            0,
                            0,
                        }
                    },
                    {
                        nItem = {
                            0,
                            0,
                            0,
                        }
                    }
                },
                nOldDeposits = {
                    0,
                    0,
                    0,
                    0,
                },
                nOldScores = {
                    0,
                    0,
                    -163116,
                    0,
                },
                nPreSaveAllDeposit = -20000,
                nScoreDiffs = {
                    0,
                    0,
                    0,
                    0,
                },
            }
        },
        {
            msgID = MyGameDef.MY_GR_SYSTEMMSG,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_46NtfMsg11",
            delay = 1,
            datatbl = {
                nChairNO         = 3,
                nEventID         = 0,
                nFangCardChairNO = 0,
                nMJID            = 0,
                nMsgID           = 4,
                nRoomID          = 0,
                nUserID          = 0,
            }
        },
        {
            msgID = MJGameDef.MJ_GR_CARD_CAUGHT,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_47ntfCardCaught9",
            delay = 1,
            datatbl = {
                dwFlags   = 0,
                nCardID   = -1,
                nCardNO   = 61,
                nChairNO  = 3,
                nReserved = {
                    0,
                    0,
                    0,
                    0,
                }
            }
        },
        {
            msgID = MJGameDef.MJ_GR_CARDS_THROW,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_48ntfCardsThrow7",
            delay = 1,
            datatbl = {
                bNextFirst  = 1,
                bNextPass   = 0,
                dwCardsType = 1,
                dwFlags = {
                    40,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                },
                nCardIDs = {
                    8
                },
                nCardsCount = 1,
                nChairNO    = 3,
                nNextChair  = 1,
                nRemains    = 13,
                nReserved = {
                    0,
                    0,
                    0,
                    0,
                },
                nThrowCount = 0,
                nUserID     = 733810,
            }
        },
        {
            msgID = MJGameDef.MJ_GR_HU_CARD,
            msgType = MSG_TYPE.RSP,
            dataFile = "RE_49rspHuCard2",
            datatbl = {
            }
        },
        {
            msgID = MyGameDef.MY_GR_SYSTEMMSG,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_50NtfMsg12",
            datatbl = {
                nChairNO         = 0,
                nEventID         = 1,
                nFangCardChairNO = 3,
                nMJID            = 8,
                nMsgID           = 3,
                nRoomID          = 0,
                nUserID          = 0,
            }
        },
        {
            msgID = MyGameDef.MY_GR_PRE_SAVE_RESULT,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_51PreSaveResult4",
            datatbl = {
                huitemhead = {
                    nChairNO           = 0,
                    nCount             = 1,
                    nPreSaveAllDeposit = 154000,
                },
                huiteminfo = {
                    {
                        bSend        = 1,
                        bWin         = 1,
                        nHuDeposits  = 6000,
                        nHuFan       = 32,
                        nHuFlag      = 1,
                        nHuGains = {
                            0,
                            0,
                            0,
                            6,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            6,
                            0,
                            0,
                            0,
                            0,
                            2,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                        },
                        nHuID        = 8,
                        nRelateChair = {
                            -1,
                            -1,
                            -1,
                            3,
                        }
                    }
                },
                hupoints = {
                    32,
                    0,
                    0,
                    -32,
                },
                nChairNO           = 0,
                nDepositDiffs = {
                    6000,
                    0,
                    0,
                    -6000,
                },
                nFlag              = 4,
                nHuStatus = {
                    {
                        nItem = {
                            268443649,
                            0,
                            262144,
                        }
                    },
                    {
                        nItem = {
                            0,
                            0,
                            0,
                        }
                    },
                    {
                        nItem = {
                            64,
                            0,
                            0,
                        }
                    },
                    {
                        nItem = {
                            0,
                            0,
                            0,
                        }
                    }
                },
                nIdlePlayerFlag    = 4,
                nOldDeposits = {
                    238000,
                    0,
                    0,
                    6000,
                },
                nOldScores = {
                    823234,
                    0,
                    0,
                    159162,
                },
                nPreSaveAllDeposit = 154000,
                nScoreDiffs = {
                    32,
                    0,
                    0,
                    -32,
                },
            }
        },
    },
    [13] = {
        {
            msgID = MyGameDef.MY_GR_PLAYING_DEPOSIT_NOT_ENOUGH,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_52ntfPlayerDepositNotEnough2",
            delay = 1,
            datatbl = {
                nGiveUpChair = {
                    -1,
                    -1,
                    -1,
                    3,
                },
                nLastSecond  = 30,
                nNeedDeposit = 30000,
            }
        },
        {
            msgID = MyGameDef.MY_GR_SYSTEMMSG,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_53NtfMsg13",
            datatbl = {
                nChairNO         = 3,
                nEventID         = 64,
                nFangCardChairNO = 0,
                nMJID            = 0,
                nMsgID           = 5,
                nRoomID          = 0,
                nUserID          = 0,
            }
        },
        {
            msgID = MyGameDef.MY_GR_PRE_SAVE_RESULT,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_54PreSaveResult5",
            datatbl = {
                hupoints = {
                    0,
                    0,
                    0,
                    0,
                },
                nChairNO           = 3,
                nDepositDiffs = {
                    0,
                    0,
                    0,
                    0,
                },
                nFlag              = 5,
                nHuStatus = {
                    {
                        nItem = {
                            268443649,
                            0,
                            262144,
                        }
                    },
                    {
                        nItem = {
                            0,
                            0,
                            0,
                        }
                    },
                    {
                        nItem = {
                            64,
                            0,
                            0,
                        }
                    },
                    {
                        nItem = {
                            64,
                            0,
                            0,
                        }
                    },
                },
                nIdlePlayerFlag    = 4,
                nOldDeposits = {
                    0,
                    0,
                    0,
                    0,
                },
                nOldScores = {
                    0,
                    0,
                    0,
                    159130,
                },
                nPreSaveAllDeposit = -70000,
                nScoreDiffs = {
                    0,
                    0,
                    0,
                    0,
                },
            }
        },
        {
            msgID = MyGameDef.MY_GR_SYSTEMMSG,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_55NtfMsg14",
            delay = 1,
            datatbl = {
                nChairNO         = 1,
                nEventID         = 0,
                nFangCardChairNO = 0,
                nMJID            = 0,
                nMsgID           = 4,
                nRoomID          = 0,
                nUserID          = 0,
            }
        },
        {
            msgID = MJGameDef.MJ_GR_CARD_CAUGHT,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_56ntfCardCaught10",
            delay = 1,
            datatbl = {
                dwFlags   = 0,
                nCardID   = -1,
                nCardNO   = 62,
                nChairNO  = 1,
                nReserved = {
                    0,
                    0,
                    0,
                    0,
                }
            }
        },
        {
            msgID = MJGameDef.MJ_GR_CARDS_THROW,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_57ntfCardsThrow8",
            delay = 1,
            datatbl = {
                bNextFirst  = 1,
                bNextPass   = 0,
                dwCardsType = 1,
                dwFlags = {
                    40,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                },
                nCardIDs = {
                    26,
                },
                nCardsCount = 1,
                nChairNO    = 1,
                nNextChair  = 0,
                nRemains    = 13,
                nReserved = {
                    0,
                    0,
                    0,
                    0,
                },
                nThrowCount = 0,
                nUserID     = 733813,
            }
        },
        {
            msgID = MJGameDef.MJ_GR_HU_CARD,
            msgType = MSG_TYPE.RSP,
            dataFile = "RE_58rspHuCard3",
            datatbl = {
            }
        },
        {
            msgID = MyGameDef.MY_GR_SYSTEMMSG,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_59NtfMsg15",
            datatbl = {
                nChairNO         = 0,
                nEventID         = 1,
                nFangCardChairNO = 1,
                nMJID            = 26,
                nMsgID           = 3,
                nRoomID          = 0,
                nUserID          = 0,
            }
        },
        {
            msgID = MyGameDef.MY_GR_PRE_SAVE_RESULT,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_60PreSaveResult6",
            datatbl = {
                huitemhead = {
                    nChairNO           = 0,
                    nCount             = 1,
                    nPreSaveAllDeposit = 160000,
                },
                huiteminfo = {
                    {
                        bSend        = 1,
                        bWin         = 1,
                        nHuDeposits  = 6000,
                        nHuFan       = 32,
                        nHuFlag      = 1,
                        nHuGains = {
                            0,
                            0,
                            0,
                            6,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            6,
                            0,
                            0,
                            0,
                            0,
                            2,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            2,
                        },
                        nHuID        = 26,
                        nRelateChair = {
                            -1,
                            1,
                            -1,
                            -1,
                        }
                    }
                },
                hupoints = {
                    32,
                    -32,
                    0,
                    0,
                },
                nChairNO           = 0,
                nDepositDiffs = {
                    6000,
                    -6000,
                    0,
                    0,
                },
                nFlag              = 4,
                nHuStatus = {
                    {
                        nItem = {
                            268443649,
                            0,
                            537133056,
                        }
                    },
                    {
                        nItem = {
                            0,
                            0,
                            0,
                        }
                    },
                    {
                        nItem = {
                            64,
                            0,
                            0,
                        }
                    },
                    {
                        nItem = {
                            64,
                            0,
                            0,
                        }
                    },
                },
                nIdlePlayerFlag    = 12,
                nOldDeposits = {
                    244000,
                    6000,
                    0,
                    0,
                },
                nOldScores = {
                    823266,
                    -36475,
                    0,
                    0,
                },
                nPreSaveAllDeposit = 160000,
                nScoreDiffs = {
                    32,
                    -32,
                    0,
                    0,
                },
            }
        },
    },
    [14] = {
        {
            msgID = MyGameDef.MY_GR_PLAYING_DEPOSIT_NOT_ENOUGH,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_61ntfPlayerDepositNotEnough3",
            delay = 1,
            datatbl = {
                nGiveUpChair = {
                    -1,
                    1,
                    -1,
                    -1,
                },
                nLastSecond  = 30,
                nNeedDeposit = 30000,
            }
        },
        {
            msgID = MyGameDef.MY_GR_SYSTEMMSG,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_62NtfMsg16",
            delay = 1,
            datatbl = {
                nChairNO         = 1,
                nEventID         = 64,
                nFangCardChairNO = 0,
                nMJID            = 0,
                nMsgID           = 5,
                nRoomID          = 0,
                nUserID          = 0,
            }
        },
        {
            msgID = BaseGameDef.BASEGAME_GR_GAME_WIN,
            msgType = MSG_TYPE.NOTIFY,
            dataFile = "RE_63ntfGameWin1",
            datatbl = {
                abortplayerinfo = {
                    {
                        nChairNO   = 0,
                        nDeposit   = 100000,
                        nLoss      = 292,
                        nNickSex   = 0,
                        nPortrait  = 0,
                        nStandOff  = 3,
                        nTableNO   = 1,
                        nUserID    = 733811,
                        nWin       = 215,
                        szUsername = "wuchen0002",
                    },
                    {
                        nChairNO   = 1,
                        nDeposit   = 80000,
                        nLoss      = 79,
                        nNickSex   = 0,
                        nPortrait  = 0,
                        nStandOff  = 0,
                        nTableNO   = 1,
                        nUserID    = 733813,
                        nWin       = 20,
                        szUsername = "wuchen0004",
                    },
                    {
                        nChairNO   = 2,
                        nDeposit   = 30000,
                        nLoss      = 81,
                        nNickSex   = 0,
                        nPortrait  = 0,
                        nStandOff  = 0,
                        nTableNO   = 1,
                        nUserID    = 733812,
                        nWin       = 24,
                        szUsername = "wuchen0003",
                    },
                    {
                        nChairNO   = 3,
                        nDeposit   = 80000,
                        nLoss      = 65,
                        nNickSex   = 0,
                        nPortrait  = 0,
                        nStandOff  = 1,
                        nTableNO   = 1,
                        nUserID    = 733810,
                        nWin       = 23,
                        szUsername = "wuchen0001",
                    },
                },
                gameEndCheckInfo = {
                    nDajiaoDePosit = {
                        0,
                        0,
                        0,
                        0,
                    },
                    nDajiaoPoint = {
                        0,
                        0,
                        0,
                        0,
                    },
                    nDrawBackDeposit = {
                        0,
                        0,
                        0,
                        0,
                    },
                    nDrawBackPoint = {
                        0,
                        0,
                        0,
                        0,
                    },
                    nFlag            = 0,
                    nHuDeposit = {
                        0,
                        0,
                        0,
                        0,
                    },
                    nHuPoint = {
                        0,
                        0,
                        0,
                        0,
                    },
                    nHuaZhuDePosit = {
                        0,
                        0,
                        0,
                        0,
                    },
                    nHuaZhuPoint = {
                        0,
                        0,
                        0,
                        0,
                    },
                    nTransferDeposit = {
                        0,
                        0,
                        0,
                        0,
                    },
                    nTransferPoint = {
                        0,
                        0,
                        0,
                        0,
                    },
                },
                gamewin = {
                    gamewin = {
                        bBankWin         = 1,
                        dwNextFlags      = 0,
                        dwWinFlags       = 1,
                        nBanker          = 1,
                        nBaseDeposit     = 2000,
                        nBaseScore       = 1,
                        nBoutCount       = 1,
                        nDepositDiffs = {
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            3268590770,
                        },
                        nIdlePlayerFlag  = 12,
                        nLevelIDs = {
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                        },
                        nNextBaseDeposit = 2000,
                        nOldDeposits = {
                            250000,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                        },
                        nOldScores = {
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                        },
                        nPartnerGroup = {
                            0,
                            1,
                            2,
                            3,
                            -1,
                            -1,
                            -1,
                            -1,
                        },
                        nScoreDiffs = {
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                        },
                        nTotalChairs     = 4,
                        nWinFees = {
                            0,
                            3268590770,
                            0,
                            3268590770,
                            0,
                            3268590770,
                            0,
                            0,
                        },
                        nWinPoints = {
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                        },
                        szLevelNames = {
                            {
                                item = ""
                            },
                            {
                                item = ""
                            },
                            {
                                item = ""
                            },
                            {
                                item = ""
                            },
                            {
                                item = ""
                            },
                            {
                                item = ""
                            },
                            {
                                item = ""
                            },
                            {
                                item = ""
                            },
                        },
                        szSerialNO       = "05b47ed47ec9e5499bdd003463e453",
                    },
                    nAnGangs = {
                        0,
                        0,
                        0,
                        0,
                    },
                    nBankerHold  = 1,
                    nChengBaoID  = 0,
                    nDetailCount = 4,
                    nHuCard      = 26,
                    nHuChair     = 0,
                    nHuChairs = {
                        1,
                        0,
                        0,
                        0,
                    },
                    nHuCount     = 1,
                    nHuaCount = {
                        0,
                        0,
                        0,
                        0,
                    },
                    nLoseChair   = 1,
                    nMnGangs = {
                        0,
                        0,
                        0,
                        0,
                    },
                    nNewRound    = 0,
                    nNextBanker  = 1,
                    nPnGangs = {
                        0,
                        0,
                        0,
                        0,
                    },
                    nResults = {
                        32,
                        0,
                        0,
                        0,
                    },
                    nTingChairs = {
                        1,
                        64,
                        64,
                        64,
                    },
                    nTingCount   = 0,
                },
                huItemhead = {
                    nChairNO           = 0,
                    nCount             = 0,
                    nPreSaveAllDeposit = 160000,
                },
                nCardsCount = {
                    13,
                    13,
                    13,
                    13,
                },
                nChairCards = {
                    {
                        item = {
                            18,
                            19,
                            11,
                            31,
                            22,
                            14,
                            5,
                            16,
                            4,
                            35,
                            34,
                            112,
                            23,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                        }
                    },
                    {
                        item = {
                            50,
                            100,
                            59,
                            42,
                            101,
                            68,
                            82,
                            63,
                            37,
                            91,
                            75,
                            86,
                            106,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                        }
                    },
                    {
                        item = {
                            102,
                            76,
                            77,
                            57,
                            13,
                            40,
                            43,
                            62,
                            64,
                            56,
                            90,
                            60,
                            25,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                        }
                    },
                    {
                        item = {
                            74,
                            83,
                            92,
                            61,
                            70,
                            44,
                            53,
                            48,
                            66,
                            71,
                            99,
                            7,
                            49,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                        }
                    }
                },
                nFees = {
                    10000,
                    10000,
                    10000,
                    10000,
                },
                nOutCards = {
                    {
                        item = {
                            {
                                nCardChair = 0,
                                nCardIDs = {
                                    -1,
                                    -1,
                                    -1,
                                    -1,
                                },
                                nType      = -1,
                            },
                            {
                                nCardChair = 0,
                                nCardIDs = {
                                    -1,
                                    -1,
                                    -1,
                                    -1,
                                },
                                nType      = -1,
                            },
                            {
                                nCardChair = 0,
                                nCardIDs = {
                                    -1,
                                    -1,
                                    -1,
                                    -1,
                                },
                                nType      = -1,
                            },
                            {
                                nCardChair = 0,
                                nCardIDs = {
                                    -1,
                                    -1,
                                    -1,
                                    -1,
                                },
                                nType      = -1,
                            },
                        }
                    },
                    {
                        item = {
                            {
                                nCardChair = 0,
                                nCardIDs = {
                                    -1,
                                    -1,
                                    -1,
                                    -1,
                                },
                                nType      = -1,
                            },
                            {
                                nCardChair = 0,
                                nCardIDs = {
                                    -1,
                                    -1,
                                    -1,
                                    -1,
                                },
                                nType      = -1,
                            },
                            {
                                nCardChair = 0,
                                nCardIDs = {
                                    -1,
                                    -1,
                                    -1,
                                    -1,
                                },
                                nType      = -1,
                            },
                            {
                                nCardChair = 0,
                                nCardIDs = {
                                    -1,
                                    -1,
                                    -1,
                                    -1,
                                },
                                nType      = -1,
                            },
                        }
                    },
                    {
                        item = {
                            {
                                nCardChair = 0,
                                nCardIDs = {
                                    -1,
                                    -1,
                                    -1,
                                    -1,
                                },
                                nType      = -1,
                            },
                            {
                                nCardChair = 0,
                                nCardIDs = {
                                    -1,
                                    -1,
                                    -1,
                                    -1,
                                },
                                nType      = -1,
                            },
                            {
                                nCardChair = 0,
                                nCardIDs = {
                                    -1,
                                    -1,
                                    -1,
                                    -1,
                                },
                                nType      = -1,
                            },
                            {
                                nCardChair = 0,
                                nCardIDs = {
                                    -1,
                                    -1,
                                    -1,
                                    -1,
                                },
                                nType      = -1,
                            }
                        }
                    },
                    {
                        item = {
                            {
                                nCardChair = 0,
                                nCardIDs = {
                                    -1,
                                    -1,
                                    -1,
                                    -1,
                                },
                                nType      = -1,
                            },
                            {
                                nCardChair = 0,
                                nCardIDs = {
                                    -1,
                                    -1,
                                    -1,
                                    -1,
                                },
                                nType      = -1,
                            },
                            {
                                nCardChair = 0,
                                nCardIDs = {
                                    -1,
                                    -1,
                                    -1,
                                    -1,
                                },
                                nType      = -1,
                            },
                            {
                                nCardChair = 0,
                                nCardIDs = {
                                    -1,
                                    -1,
                                    -1,
                                    -1,
                                },
                                nType      = -1,
                            }
                        }
                    },
                },
                nOutCount = {
                    0,
                    0,
                    0,
                    0,
                },
                nTotalDepositDiff = {
                    160000,
                    -70000,
                    -20000,
                    -70000,
                },
            }
        },
        {
            msgID = CUSTOM_MSG_ID.GETREWARD,
            msgType = MSG_TYPE.CUSTOM,
        },
        {
            msgID = CUSTOM_MSG_ID.LESSONOVER,
            msgType = MSG_TYPE.CUSTOM,
        },
    }
}

return {lessonData, MSG_TYPE, CUSTOM_MSG_ID}