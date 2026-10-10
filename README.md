# MaiFocus FTP Edge Agent

Sanitized source backup of the Edge Agent, RTSP Snapshot Service, camera
simulator, webhook receiver, and Windows customer installation scripts.

The installation baseline is **3.18**. The `v3.18-backup.1` GitHub release contains
rebuilt Windows executables and a sanitized installation kit. It is a backup
distribution, not a new feature release.

## Contents

- Root Python files: Edge Agent, FTP receiver, and camera simulator.
- `rtsp_snapshot_service/`: RTSP snapshots and RTMP relay source.
- `webhook_server/`: example webhook receiver source.
- `MaiFocus-Customer-PC-Install-Kit/`: full installation scripts and bundled source.
- `package/` and platform package folders: original packaging source variants.

## Customer configuration

No live customer configuration, tokens, environment files, images, logs, or
databases are included. `agent.env.example` is a placeholder template.
The distributed `cameras.json` files contain an empty camera list, a placeholder
RTSP password, and an empty API token. The CSV contains disabled example rows.

Before a new installation, configure `00-MASTER-CONFIG.ps1` and the camera list
locally. The FTP password in this backup is `CHANGE_ME_FTP_PASSWORD`; replace it
with a unique password and configure cameras to use the same value. Configure
webhook URLs and tokens for the customer. Do not commit filled configuration
templates. Existing deployment configuration is not part of this backup.

Run `RUN-ALL-AS-ADMIN.bat` on the target Windows PC after configuration; see the
installation kit's Hebrew instructions. Installation was not run on a customer
PC as part of this backup.

## Release assets

Large executables and ZIPs are stored in GitHub Releases rather than Git history.
The release includes the full install kit, standalone Edge Agent, RTSP service,
camera simulator, GCP helpers, source archive, and SHA-256 checksums.
Old customer ZIPs and build caches were deliberately excluded.

## Verification

Source is scanned with Gitleaks. Packaged Python constants are inspected from
the PyInstaller archives, along with the configuration shipped in the ZIPs.
These checks reduce accidental disclosure; they are not a security audit of
the application or its dependencies.
