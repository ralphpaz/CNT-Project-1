import socket
import threading
import time
from collections import deque

BUFFER_SIZE = 65535


def parse_server_response(response):
    """Split 'status\n\ndata' into status and data."""
    parts = response.split("\n\n", 1)
    status_code = parts[0].strip()
    data = parts[1].strip() if len(parts) > 1 else ""
    return status_code, data


def receive_message(sock):
    """Receive a server response using a large buffer to avoid truncated output."""
    data = sock.recv(BUFFER_SIZE)
    if data == b"":
        return ""
    return data.decode()


def command_name(command):
    parts = command.split()
    return parts[0] if parts else ""


def print_success_for_command(command, data):
    """Print successful command responses using the required client output template."""
    name = command_name(command)

    if name == "login":
        print("200 status code received. Login successful")
    elif name == "who":
        print(f"200 status code received. Users currently connected: {data}")
    elif name == "private":
        print("200 status code received. Message sent.")
    elif name == "quit":
        print("200 status code received.")
    else:
        print("200 status code received.")
        if data != "":
            print(data)


def print_failure(data):
    print("500 status code received.")
    if data != "":
        print(data)


def pop_pending_command(pending_commands, lock):
    with lock:
        if len(pending_commands) == 0:
            return None
        return pending_commands.popleft()


def peek_pending_command(pending_commands, lock):
    with lock:
        if len(pending_commands) == 0:
            return None
        return pending_commands[0]


def set_pending_done(pending_item):
    if pending_item is not None:
        pending_item["event"].set()


def print_prompt():
    print("> ", end="", flush=True)


def listen_for_server_messages(data_socket, pending_commands, lock):
    """Continuously receive DATA responses and asynchronous messages."""
    while True:
        try:
            response = receive_message(data_socket)
        except ConnectionResetError:
            break
        except OSError:
            break

        if response == "":
            break

        status_code, data = parse_server_response(response)

        if status_code != "200":
            pending_item = pop_pending_command(pending_commands, lock)
            print_failure(data)
            set_pending_done(pending_item)
            continue

        if data.startswith("Broadcast\n"):
            pending_item = None
            pending = peek_pending_command(pending_commands, lock)
            if pending is not None and command_name(pending["command"]) == "broadcast":
                pending_item = pop_pending_command(pending_commands, lock)

            lines = data.split("\n", 2)
            print("200 status code received.")
            if len(lines) == 3:
                sender = lines[1]
                message = lines[2]
                print(f"Broadcast message from {sender}: {message}")
            else:
                print(data)

            if pending_item is None:
                print_prompt()
            else:
                set_pending_done(pending_item)

        elif data.startswith("Private\n"):
            lines = data.split("\n", 2)
            print("200 status code received.")
            if len(lines) == 3:
                sender = lines[1]
                message = lines[2]
                print(f"{sender}: {message}")
            else:
                print(data)
            print_prompt()

        elif data.startswith("join\n"):
            lines = data.split("\n", 1)
            print("200 status code received.")
            if len(lines) == 2:
                print(f"{lines[1]} joined the chat")
            else:
                print(data)
            print_prompt()

        elif data.startswith("Logout\n"):
            lines = data.split("\n", 1)
            print("200 status code received.")
            if len(lines) == 2:
                print(f"{lines[1]} left the chat")
            else:
                print(data)
            print_prompt()

        else:
            pending_item = pop_pending_command(pending_commands, lock)
            if pending_item is not None:
                print_success_for_command(pending_item["command"], data)
                set_pending_done(pending_item)
            else:
                print("200 status code received.")
                if data != "":
                    print(data)
                print_prompt()


def main():
    print("Starting client…")

    command = input("> ")
    parts = command.split()

    if len(parts) != 3 or parts[0] != "connect":
        print("Invalid command. Use: connect <ip> <port>")
        return

    server_ip = parts[1]
    control_port = int(parts[2])

    control_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    control_socket.connect((server_ip, control_port))
    control_socket.sendall(command.encode())

    response = receive_message(control_socket)
    status_code, data_port = parse_server_response(response)

    if status_code != "200":
        print("500 status code received. Connection failed")
        control_socket.close()
        return

    print(f"200 status code received. Starting data connection on port {data_port}")

    data_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    data_socket.connect((server_ip, int(data_port)))

    pending_commands = deque()
    lock = threading.Lock()

    listener_thread = threading.Thread(
        target=listen_for_server_messages,
        args=(data_socket, pending_commands, lock),
        daemon=True
    )
    listener_thread.start()

    while True:
        command = input("> ")

        if command.strip() == "":
            continue

        pending_item = {
            "command": command,
            "event": threading.Event()
        }

        with lock:
            pending_commands.append(pending_item)

        control_socket.sendall(command.encode())

        # Wait until the listener prints this command's response before taking
        # another command. This prevents command responses from piling up and
        # fixes incomplete/incorrect who output when commands are entered quickly.
        pending_item["event"].wait(timeout=5)

        if command.strip() == "quit":
            time.sleep(0.1)
            break

    data_socket.close()
    control_socket.close()


if __name__ == "__main__":
    main()
