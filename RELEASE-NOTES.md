Sanitized backup of MaiFocus version 3.18, prepared on 2026-10-10.

Includes source code, the full Windows installation kit, rebuilt Edge Agent,
RTSP Snapshot Service, camera simulator, and GCP helpers. Executables are stored
in release assets because of their size. SHA256SUMS.txt covers every ZIP.

Customer camera lists, passwords, tokens, private environment files, databases,
images, logs, and old build caches are excluded. Camera configuration is blank;
the FTP password is the placeholder CHANGE_ME_FTP_PASSWORD. Configure customer
settings locally before installation. The original customer installation files
have not been modified.

Validation: Gitleaks source scan, Python and PowerShell syntax checks, and
inspection of application constants inside the rebuilt PyInstaller binaries.
This backup has not been tested on the customer's Windows device or cameras.
