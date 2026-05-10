# Match Data Structure Definitions

Received from gamesvrDev at 2026-04-22

---

## 1. Match Request JSON

```json
{
  "action": "match_join",
  "player_id": 10001,
  "player_info": {
    "nickname": "PlayerName",
    "avatar": "url",
    "score": 1500,
    "level": 5
  },
  "match_type": "rank",
  "game_mode": "sichuan_mj"
}
```

---

## 2. Match Response JSON

```json
{
  "result": 0,
  "message": "success",
  "data": {
    "match_id": "M_20260422_001",
    "status": 1,
    "queue_position": 3,
    "estimated_wait": 15
  }
}
```

---

## 3. Match Status Enum

| Value | Status |
|-------|--------|
| 0 | idle |
| 1 | queuing |
| 2 | matching |
| 3 | matched |
| 4 | entering |
| 5 | canceled |
| 6 | timeout |

---

## 4. Player Match Info Fields

```json
{
  "player_id": 10001,
  "nickname": "string",
  "avatar": "string",
  "score": 1500,
  "level": 5,
  "win_rate": 0.55,
  "match_history_count": 120
}
```

---

## 5. Match Result Push

```json
{
  "event": "match_result",
  "data": {
    "match_id": "M_001",
    "status": 3,
    "room_id": "R_12345",
    "players": [
      {"player_id": 10001, "seat": 0}
    ],
    "server_ip": "192.168.1.100",
    "server_port": 8100
  }
}
```
