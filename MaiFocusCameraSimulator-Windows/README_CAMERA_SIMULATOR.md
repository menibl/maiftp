# MaiFocus Camera Simulator

This tool simulates a camera/NVR that uploads images to the local FTP agent.

Use it on a second Windows computer in the same LAN as the computer running
`MaiFocusEdgeAgent`.

## Settings

```text
FTP Server IP: local IP shown in MaiFocusEdgeAgent
Port: 2121
Username: hikvision
Password: CHANGE_ME_FTP_PASSWORD
Remote Folder: /
Passive FTP: ON
```

Click `Upload Once` to send one test image.

Click `Start Loop` to upload an image every configured interval.

If `Image File` is empty, the simulator creates a generated test image with
timestamp and camera name.
