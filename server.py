import socket
import sys
import threading

def format_response(status_code, data=""): 

    if data == "":
        return f"{status_code}\n\n"
    else: 
        return f"{status_code}\n\n{data}"
    
def create_data_socket():

    data_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    data_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    data_socket.bind(("",0))
    data_socket.listen()

    data_port = data_socket.getsockname()[1] 

    return data_socket, data_port

def handle_login(parts, client_control_socket, client_data_socket, active_clients, clients_lock, current_username):
    if len(parts) != 2: 
        response = format_response(500, "Invalid login command")
        client_data_socket.sendall(response.encode())
        return current_username
    
    requested_username = parts[1]

    print(f"Login requested by: {requested_username}")

    if current_username is not None: 
        response = format_response(500, "User already logged in")
        client_data_socket.sendall(response.encode())
        return current_username
    
    with clients_lock:
        if requested_username in active_clients:
            response = format_response(500, "Username already taken")
            client_data_socket.sendall(response.encode())
            return current_username
    
        active_clients[requested_username] = {
            "control_socket": client_control_socket,
            "data_socket": client_data_socket
        }

    response = format_response(200)
    client_data_socket.sendall(response.encode())

    return requested_username


def handle_client_commands(client_control_socket, client_data_socket, active_clients, clients_lock):

    current_username = None 

    while True: 

        try: 
            command = client_control_socket.recv(1024).decode().strip()
        except ConnectionResetError:
            break

        if command == "":
            break

        parts = command.split()

        if len(parts) == 0: 
            continue

        command_name = parts[0] 

        # login command placeholder
        if command_name == "login":
            
            current_username = handle_login(
                parts,
                client_control_socket,
                client_data_socket,
                active_clients,
                clients_lock,
                current_username
            )

        # who command placeholder
        elif command_name == "who":
            print("Who requested. Sending users.")

            if current_username is None:
                response = format_response(500, "You must login first")
            else:
                with clients_lock:
                    users = ", ".join(active_clients.keys())
                
                response = format_response(200, users)

            client_data_socket.sendall(response.encode())

        elif command_name == "broadcast": 
            if current_username is None:
                response = format_response(500, "You must login first")
                client_data_socket.sendall(response.encode())

            elif len(parts) < 2: 
                response = format_response(500, "Invalid broadcast command")
                client_data_socket.sendall(response.encode())

            else:
                print(f"Broadcast requested by {current_username}")

                message = " ".join(parts[1:])

                print(f"Message: {message}")

                broadcast_data = f"Broadcast\n{current_username}\n{message}"
                response = format_response(200, broadcast_data)

                with clients_lock:
                    recipient_sockets = [
                        client_info["data_socket"]
                        for client_info in active_clients.values()
                    ]

                for recipient_socket in recipient_sockets:
                    recipient_socket.sendall(response.encode()) 


        
        # private command placeholder 
        elif command_name == "private": 
            if current_username is None:
                response = format_response(500, "You must login first")
                client_data_socket.sendall(response.encode())
            
            elif len(parts) < 3: 
                response = format_response(500, "Invalid private command")
                client_data_socket.sendall(response.encode())
            
            else: 
                recipient_username = parts[1]
                message = " ".join(parts[2:])

                print(f"Private message from {current_username} to {recipient_username}")

                with clients_lock:
                    if recipient_username not in active_clients:
                        recipient_socket = None
                    else: 
                        recipient_socket = active_clients[recipient_username]["data_socket"]
                
                if recipient_socket is None: 
                    response = format_response(500, "User does not exist")
                    client_data_socket.sendall(response.encode())
                
                else:
                    private_data = f"Private\n{current_username}\n{message}" 
                    recipient_response = format_response(200, private_data)

                    recipient_socket.sendall(recipient_response.encode())

                    sender_response = format_response(200)
                    client_data_socket.sendall(sender_response.encode())
        
        # quit 
        elif command_name == "quit":
            if current_username is not None:
                print(f"Quit requested by {current_username}")

                with clients_lock:
                    if current_username in active_clients:
                        del active_clients[current_username]

                    remaining_sockets = [
                        client_info["data_socket"]
                        for client_info in active_clients.values()
                    ]

                response = format_response(200)
                client_data_socket.sendall(response.encode())

                logout_data = f"Logout\n{current_username}"
                logout_response = format_response(200, logout_data)

                for recipient_socket in remaining_sockets:
                    try: 
                        recipient_socket.sendall(logout_response.encode())
                    except OSError:
                        pass
            else:
                print("Quit requested")

                response = format_response(200)
                client_data_socket.sendall(response.encode())

            break

        # unknown command
        else:
            response = format_response(500, "Unknown command")
            client_data_socket.sendall(response.encode())

    if current_username is not None: 
        with clients_lock:
            if current_username in active_clients:
                del active_clients[current_username]


def handle_new_client(client_control_socket, client_address, active_clients, clients_lock):

    data_socket = None
    client_data_socket = None

    try: 
        command = client_control_socket.recv(1024).decode().strip()

        parts = command.split()

        if len(parts) == 3 and parts[0] == "connect":
            print("Connection requested. Creating data socket")

            data_socket, data_port = create_data_socket()

            response = format_response(200, str(data_port))
            client_control_socket.sendall(response.encode())

            client_data_socket, client_data_address = data_socket.accept()
            
            print("Data connection established with:", client_data_address)

            handle_client_commands(
                client_control_socket, 
                client_data_socket, 
                active_clients,
                clients_lock
            )
        
        else: 
            response = format_response(500, "Invalid connect command")
            client_control_socket.sendall(response.encode())
        
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

    print("Starting server...")
    print("Creating server socket")

    control_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    control_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    control_socket.bind(("", control_port))
    control_socket.listen()

    print("Awaiting connections...")

    while True: 
        client_control_socket, client_address = control_socket.accept()

        client_thread = threading.Thread(
            target=handle_new_client, 
            args=(client_control_socket, client_address, active_clients, clients_lock)
        )

        client_thread.start()


if __name__ == "__main__": 
    main()


