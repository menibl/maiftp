# -*- coding: utf-8 -*-
import os
try:
    from pyftpdlib.authorizers import DummyAuthorizer
    from pyftpdlib.handlers import FTPHandler
    from pyftpdlib.servers import FTPServer
except ImportError:
    print("[!] Error: pyftpdlib is not installed.")
    print("[*] Please run: pip install pyftpdlib")
    input("Press Enter to exit...")
    exit(1)

def main():
    # Create a local directory to store the incoming Hikvision images
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hikvision_images")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"[*] Created directory for images: {output_dir}")

    # Instantiate a dummy authorizer for managing virtual users
    authorizer = DummyAuthorizer()

    # Define a user with full read/write permissions for Hikvision camera
    # Permissions: 'elradfmwMT' (full write and read access)
    authorizer.add_user('hikvision', 'CHANGE_ME_FTP_PASSWORD', output_dir, perm='elradfmwMT')
    print("[*] User configured: username='hikvision', password='CHANGE_ME_FTP_PASSWORD'")

    # Instantiate FTP handler class
    handler = FTPHandler
    handler.authorizer = authorizer
    handler.banner = "Hikvision Testing FTP Server Ready."
    handler.passive_ports = range(50000, 50101)

    masquerade_address = os.environ.get("FTP_PUBLIC_IP")
    if masquerade_address:
        handler.masquerade_address = masquerade_address
        print(f"[*] Public FTP address configured: {masquerade_address}")

    # Define the port (2121 is used to avoid needing Administrator privileges on Windows)
    PORT = 2121
    server = FTPServer(('0.0.0.0', PORT), handler)

    print(f"\n[+] FTP Server is RUNNING on port {PORT}...")
    print("[*] Set this Port to 2121 in your Hikvision FTP settings.")
    print("[*] Passive FTP data ports: 50000-50100.")
    print("[*] Incoming snapshots will be saved directly to the 'hikvision_images' folder.\n")
    print("[>] Press Ctrl+C to stop the server.")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[-] FTP Server stopped.")

if __name__ == '__main__':
    main()
