import socket
import sys
import threading

BUFFER_SIZE = 65535


def format_response(status_code, data=""):
    if data == "":
        return f"{status_code}\n\n"
    return f"{status_code}\n\n{data}"


def safe_send(sock, message, send_lock):
    with send_lock:
        sock.sendall(message.encode())


def create_data_socket():
    data_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    data_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    data_socket.bind(("", 0))
    data_socket.listen()
    data_port = data_socket.getsockname()[1]
    return data_socket, data_port


def handle_login(parts, client_control_socket, client_data_socket,
                 active_clients, clients_lock, send_lock, current_username):
    if len(parts) != 2:
        safe_send(client_data_socket, format_response(500, "Invalid login command"), send_lock)
        return current_username

    requested_username = parts[1]
    print(f"Login requested by: {requested_username}", flush=True)

    if current_username is not None:
        safe_send(client_data_socket, format_response(500, "User already logged in"), send_lock)
        return current_username

    with clients_lock:
        if requested_username in active_clients:
            safe_send(client_data_socket, format_response(500, "Username already taken"), send_lock)
            return current_username

        active_clients[requested_username] = {
            "control_socket": client_control_socket,
            "data_socket": client_data_socket
        }

        other_sockets = [
            client_info["data_socket"]
            for username, client_info in active_clients.items()
            if username != requested_username
        ]

    # The logging-in client receives only a successful status code.
    safe_send(client_data_socket, format_response(200), send_lock)

    # The project requires a join notification to already-connected clients.
    join_response = format_response(200, f"join\n{requested_username}")
    for recipient_socket in other_sockets:
        try:
            safe_send(recipient_socket, join_response, send_lock)
        except OSError:
            pass

    return requested_username


def handle_who(client_data_socket, active_clients, clients_lock, send_lock, current_username):
    print("Who requested. Sending users.", flush=True)

    if current_username is None:
        safe_send(client_data_socket, format_response(500, "You must login first"), send_lock)
        return

    with clients_lock:
        users = ", ".join(active_clients.keys())

    safe_send(client_data_socket, format_response(200, users), send_lock)


def handle_broadcast(parts, client_data_socket, active_clients, clients_lock,
                     send_lock, current_username):
    if current_username is None:
        safe_send(client_data_socket, format_response(500, "You must login first"), send_lock)
        return

    if len(parts) < 2:
        safe_send(client_data_socket, format_response(500, "Invalid broadcast command"), send_lock)
        return

    print(f"Broadcast requested by {current_username}", flush=True)

    message = " ".join(parts[1:])
    print(f"Message: {message}", flush=True)

    response = format_response(200, f"Broadcast\n{current_username}\n{message}")

    with clients_lock:
        recipient_sockets = [
            client_info["data_socket"]
            for client_info in active_clients.values()
        ]

    for recipient_socket in recipient_sockets:
        try:
            safe_send(recipient_socket, response, send_lock)
        except OSError:
            pass


def handle_private(parts, client_data_socket, active_clients, clients_lock,
                   send_lock, current_username):
    if current_username is None:
        safe_send(client_data_socket, format_response(500, "You must login first"), send_lock)
        return

    if len(parts) < 3:
        safe_send(client_data_socket, format_response(500, "Invalid private command"), send_lock)
        return

    recipient_username = parts[1]
    message = " ".join(parts[2:])

    print(f"Private message from {current_username} to {recipient_username}", flush=True)

    with clients_lock:
        recipient_info = active_clients.get(recipient_username)
        recipient_socket = None if recipient_info is None else recipient_info["data_socket"]

    if recipient_socket is None:
        safe_send(client_data_socket, format_response(500, "User does not exist"), send_lock)
        return

    recipient_response = format_response(200, f"Private\n{current_username}\n{message}")
    try:
        safe_send(recipient_socket, recipient_response, send_lock)
    except OSError:
        safe_send(client_data_socket, format_response(500, "User does not exist"), send_lock)
        return

    # The sender receives only a successful status code.
    safe_send(client_data_socket, format_response(200), send_lock)


def handle_quit(client_data_socket, active_clients, clients_lock, send_lock, current_username):
    if current_username is not None:
        print(f"Quit requested by {current_username}", flush=True)

        with clients_lock:
            if current_username in active_clients:
                del active_clients[current_username]

            remaining_sockets = [
                client_info["data_socket"]
                for client_info in active_clients.values()
            ]

        safe_send(client_data_socket, format_response(200), send_lock)

        logout_response = format_response(200, f"Logout\n{current_username}")
        for recipient_socket in remaining_sockets:
            try:
                safe_send(recipient_socket, logout_response, send_lock)
            except OSError:
                pass
    else:
        print("Quit requested", flush=True)
        safe_send(client_data_socket, format_response(200), send_lock)


def handle_client_commands(client_control_socket, client_data_socket,
                           active_clients, clients_lock, send_lock):
    current_username = None

    while True:
        try:
            command = client_control_socket.recv(BUFFER_SIZE).decode().strip()
        except ConnectionResetError:
            break

        if command == "":
            break

        parts = command.split()
        if len(parts) == 0:
            continue

        command_name = parts[0]

        if command_name == "login":
            current_username = handle_login(
                parts,
                client_control_socket,
                client_data_socket,
                active_clients,
                clients_lock,
                send_lock,
                current_username
            )

        elif command_name == "who":
            handle_who(client_data_socket, active_clients, clients_lock, send_lock, current_username)

        elif command_name == "broadcast":
            handle_broadcast(parts, client_data_socket, active_clients, clients_lock,
                             send_lock, current_username)

        elif command_name == "private":
            handle_private(parts, client_data_socket, active_clients, clients_lock,
                           send_lock, current_username)

        elif command_name == "quit":
            handle_quit(client_data_socket, active_clients, clients_lock, send_lock, current_username)
            break

        else:
            safe_send(client_data_socket, format_response(500, "Unknown command"), send_lock)

    # Cleanup if the client disconnects without sending quit.
    if current_username is not None:
        with clients_lock:
            if current_username in active_clients:
                del active_clients[current_username]


def handle_new_client(client_control_socket, client_address,
                      active_clients, clients_lock, send_lock):
    data_socket = None
    client_data_socket = None

    try:
        command = client_control_socket.recv(BUFFER_SIZE).decode().strip()
        parts = command.split()

        if len(parts) == 3 and parts[0] == "connect":
            print("Connection requested. Creating data socket", flush=True)

            data_socket, data_port = create_data_socket()
            safe_send(client_control_socket, format_response(200, str(data_port)), send_lock)

            client_data_socket, client_data_address = data_socket.accept()

            handle_client_commands(
                client_control_socket,
                client_data_socket,
                active_clients,
                clients_lock,
                send_lock
            )
        else:
            safe_send(client_control_socket, format_response(500, "Invalid connect command"), send_lock)

    finally:
        if client_data_socket is not None:
            client_data_socket.close()
        if data_socket is not None:
            data_socket.close()
        client_control_socket.close()


def main():
    if len(sys.argv) != 2:
        print("Usage: python server.py <port>")
        return

    control_port = int(sys.argv[1])
    active_clients = {}
    clients_lock = threading.Lock()
    send_lock = threading.Lock()

    print("Starting server…", flush=True)
    print("Creating server socket", flush=True)

    control_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    control_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    control_socket.bind(("", control_port))
    control_socket.listen()

    print("Awaiting connections…", flush=True)

    while True:
        client_control_socket, client_address = control_socket.accept()

        client_thread = threading.Thread(
            target=handle_new_client,
            args=(client_control_socket, client_address, active_clients, clients_lock, send_lock),
            daemon=True
        )
        client_thread.start()


if __name__ == "__main__":
    main()
