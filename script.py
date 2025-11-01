# ...existing code...
import socket
import struct
import cv2
import numpy as np
import time

BIND_IP = "0.0.0.0"
BIND_PORT = 3333            # must match ESP32 target_port
MARKER = 0xDEADBEEF
MARKER_B = struct.pack("<I", MARKER)

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
# increase kernel recv buffer to reduce drops
sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
sock.bind((BIND_IP, BIND_PORT))
sock.settimeout(0.5)

print(f"Listening UDP {BIND_IP}:{BIND_PORT}")

# reassembly state
expecting = False
frame_size = 0
frame_buf = None
have = None
have_count = 0

frame_count = 0
last_addr = None
start_time = time.time()

try:
    while True:
        try:
            data, addr = sock.recvfrom(65536)
            # optional: comment out the per-packet debug for speed
            # print(f"Pkt {len(data)} from {addr}")
            last_addr = addr
        except socket.timeout:
            data = b''

        if not data:
            pass
        else:
            mpos = data.find(MARKER_B)
            if data.startswith(MARKER_B):
                # header: marker(4) + size(4) + offset(4)
                if len(data) >= 12:
                    frame_size = struct.unpack_from("<I", data, 4)[0]
                    offset = struct.unpack_from("<I", data, 8)[0]
                    payload = data[12:]
                    # start new frame
                    expecting = True
                    frame_buf = bytearray(frame_size)
                    have = bytearray(frame_size)  # bytes 0/1
                    have_count = 0
                    if payload and offset < frame_size:
                        end = min(frame_size, offset + len(payload))
                        length = end - offset
                        frame_buf[offset:end] = payload[:length]
                        have[offset:end] = b'\x01' * length
                        have_count += length
                else:
                    # header split across packets - ignore
                    pass
            else:
                # chunk: first 4 bytes = offset
                if expecting and len(data) >= 4:
                    offset = struct.unpack_from("<I", data, 0)[0]
                    payload = data[4:]
                    if offset < frame_size and payload:
                        end = min(frame_size, offset + len(payload))
                        length = end - offset
                        prev = have[offset:end]
                        newly = length - prev.count(1)
                        if newly > 0:
                            frame_buf[offset:end] = payload[:length]
                            have[offset:end] = b'\x01' * length
                            have_count += newly
                else:
                    # no active frame - ignore
                    pass

        # complete?
        # complete?
        if expecting and frame_size > 0 and have_count >= frame_size:
            jpg = bytes(frame_buf)

            # quick SOI/EOI check and log
            soi = jpg[:2].hex()
            eoi = jpg[-2:].hex()
            if soi != "ffd8" or eoi != "ffd9":
                print(f"JPEG SOI/EOI mismatch: SOI={soi} EOI={eoi} size={len(jpg)} have_count={have_count}/{frame_size}")

            # save received JPEG for inspection
            try:
                with open("/tmp/last_frame.jpg", "wb") as f:
                    f.write(jpg)
                print(f"Saved /tmp/last_frame.jpg ({len(jpg)} bytes)")
            except Exception as e:
                print("Failed to write /tmp/last_frame.jpg:", e)

            # try decode
            img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
            frame_count += 1
            elapsed = time.time() - start_time
            if img is None:
                print(f"[{frame_count}] decode FAILED size={len(jpg)} from={last_addr} time={elapsed:.2f}s")
                # show a short hex preview
                print("first 64 bytes:", jpg[:64].hex())
            else:
                print(f"[{frame_count}] frame {len(jpg)} bytes from {last_addr} time={elapsed:.2f}s")
                cv2.imshow("ESP32 UDP Stream", img)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

            # reset state for next frame
            expecting = False
            frame_size = 0
            frame_buf = None
            have = None
            have_count = 0

except KeyboardInterrupt:
    print("stopping")
finally:
    sock.close()
    cv2.destroyAllWindows()
# ...existing code...