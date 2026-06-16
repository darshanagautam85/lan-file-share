# lan-file-share
# LAN File Share

A Python-based LAN File Sharing Application that allows users to send and receive files over the same local network (LAN) using a graphical user interface built with Tkinter.

The application provides real-time connection monitoring, transfer progress tracking, speed calculation, ETA estimation, transfer history logs, and manual file acceptance for secure transfers.

---

## Features

- Send files between devices connected to the same LAN
- Modern GUI built with Tkinter
- Real-time transfer progress bar
- Transfer speed monitoring
- Estimated Time Remaining (ETA)
- Incoming file request approval system
- Connection status monitoring
- Sender and Receiver connection cards
- Transfer history logging
- Transfer cancellation support
- Automatic IP detection
- Ping-based device availability check
- Multi-threaded file transfers
- Large file support

---

## Technologies Used

- Python 3
- Tkinter
- Socket Programming
- Multithreading
- Queue Management

---

## How It Works

### Sender

1. Enter receiver's IP address.
2. Ping receiver to verify availability.
3. Select a file.
4. Send file.

### Receiver

1. Application listens for incoming connections.
2. Incoming transfer request appears.
3. User can accept or decline transfer.
4. File is saved to selected location.

---

## Project Structure

LAN-File-Share/
│
├── lan_file_share.py
├── README.md
└── LICENSE

---

## Key Functionalities

### Connection Monitoring
Tracks sender and receiver connection status in real-time.

### File Transfer
Transfers files over TCP sockets.

### Transfer Statistics
Displays:
- Progress Percentage
- Transfer Speed
- ETA

### Security Layer
Receiver must manually approve incoming files before transfer begins.

### Transfer History
Maintains logs of sent and received files.

---

## Future Improvements

- End-to-end encryption
- Drag and drop support
- File transfer resume feature
- Multiple file transfer support
- Dark mode
- Cross-platform packaging
- User authentication
- QR code based connection


## Author

Darshana Gautam

Cybersecurity Enthusiast | Python Developer

---

## License

This project is licensed under the MIT License.
