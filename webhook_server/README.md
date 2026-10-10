# MaiFocus Webhook Server

שרת בדיקה/בסיס לקבלת תמונות מה-Agent המקומי.

## התקנה

```powershell
cd C:\ftpropin\webhook_server
python -m pip install -r requirements.txt
```

## הפעלה

```powershell
.\run_server.ps1
```

השרת יעלה על:

```text
http://localhost:8088
```

## הגדרות ב-Agent

```text
Webhook URL: http://SERVER-IP:8088/webhook/image
Heartbeat URL: http://SERVER-IP:8088/webhook/heartbeat
Remote Command URL: http://SERVER-IP:8088/webhook/commands
```

## צפייה בנתונים

```text
GET /images
GET /images?alert_only=true
GET /images/{id}
GET /images/{id}/file
GET /heartbeats
GET /commands
```

## יצירת פקודה מרחוק

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:8088/commands `
  -ContentType application/json `
  -Body '{"agent_id":"PC-NAME","action":"status","args":{}}'
```

פקודות נתמכות ב-Agent:

```text
status
list_files
delete_file
delete_all_images
restart_ftp
```
