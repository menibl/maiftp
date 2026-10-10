# Local FTP Agent

התוכנה הזו מיועדת לרוץ בתוך הרשת המקומית של המצלמות.

הזרימה:

1. המצלמה שולחת תמונות לשרת ה-FTP המקומי.
2. הקבצים נשמרים בתיקייה `hikvision_images`.
3. `local_agent.py` מזהה תמונות חדשות.
4. ה-Agent שולח את התמונה לשרת שלך ב-Webhook.
5. אופציונלית: אפשר להפעיל YOLO מקומי ולשלוח גם detections.

## התקנה

```powershell
cd C:\ftpropin
python -m pip install -r requirements.txt
```

אם רוצים YOLO מקומי:

```powershell
python -m pip install -r requirements-yolo.txt
```

## הגדרות

צור קובץ `agent.env` מתוך הדוגמה:

```powershell
Copy-Item .\agent.env.example .\agent.env
notepad .\agent.env
```

עדכן לפחות את:

```text
WEBHOOK_URL=https://your-server.example/webhook
SOURCE_NAME=customer-site-1
```

## הפעלה

חלון ראשון:

```powershell
cd C:\ftpropin
python .\ftp_server.py
```

חלון שני:

```powershell
cd C:\ftpropin
.\run_agent.ps1
```

## מבנה ה-Webhook

ה-Agent שולח בקשת `POST multipart/form-data`:

```text
image   = קובץ התמונה
payload = JSON עם metadata
```

דוגמת `payload`:

```json
{
  "source": "customer-site-1",
  "filename": "image001.jpg",
  "relative_path": "image001.jpg",
  "size": 123456,
  "sha256": "...",
  "created_at_utc": "...",
  "modified_at_utc": "...",
  "sent_at_utc": "...",
  "detections": []
}
```

## הפעלת YOLO

בקובץ `agent.env`:

```text
ENABLE_YOLO=1
YOLO_MODEL=yolov8n.pt
```

אפשר גם לשים נתיב למודל מותאם אישית:

```text
YOLO_MODEL=C:\models\best.pt
```

## הערה חשובה

ה-Agent שומר קובץ מצב בשם `agent_state.sqlite3`, ולכן הוא לא ישלח שוב קבצים שכבר נשלחו בהצלחה גם אחרי הפעלה מחדש.
