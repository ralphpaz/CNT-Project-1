import socket
import threading
import time

def parse_server_response(response):

    parts = response.split("\n\n", 1)

    status_code = parts[0].strip()

    if len(parts) > 1: 
        
        data = parts[1].strip()

    else: 
        
        data = ""

    return status_code, data


def print_response_for_command(command, status_code, data):

    command_parts = command.split()

    if len(command_parts) == 0:
        return 
    
    command_name = command_parts[0]

    if status_code == "200":
        
        if command_name == "login":
            print(f"200 status code received. Login successful")

        elif command_name == "who":
            print(f"200 status code received. Users currently connected: {data}")
        
        elif command_name == "broadcast":
            print("200 status code received")
        
            if data != "":
                print(data)
        
        elif command_name == "private":
            print("200 status code received. Message sent.")
        
        elif command_name == "quit":
            print("200 status code received")

        else:
            print("200 status code received.")

            if data != "":
                print(data)

    else: 
        print("500 status code received.")

        if data != "": 
            print(data)


def listen_for_server_messages(data_socket):

    while True: 
        try: 
            response = data_socket.recv(1024).decode()
        except ConnectionResetError:
            break
        except OSError:
            break

        if response == "":
            break

        status_code, data = parse_server_response(response)

        if status_code == "200":
            if data.startswith("Broadcast\n"):
                lines = data.split("\n", 2)

                if len(lines) == 3:
                    sender = lines[1]
                    message = lines[2]
                    print()
                    print("200 status code received.")
                    print(f"Broadcast message from {sender}: {message}")
                    print("> ", end="", flush=True)
                else:
                    print()
                    print("200 status code received")
                    print(data)
                    print("> ", end="", flush=True)
            
            elif data.startswith("Private\n"):
                lines = data.split("\n", 2)

                if len(lines) == 3: 
                    sender = lines[1]
                    message = lines[2]

                    print()
                    print("200 status code received.")
                    print(f"{sender}: {message}")
                    print("> ", end="", flush=True)

                else: 
                    print()
                    print("200 status code received.")
                    print(data)
                    print("> ", end="", flush=True)
                
            elif data.startswith("Logout\n"):
                lines = data.split("\n", 1)

                if len(lines) == 2:
                    username = lines[1]

                    print()
                    print("200 status code received.")
                    print(f"{username} left the chat")
                    print("> ", end="", flush=True)
                
                else: 
                    print()
                    print("200 status code received.")
                    print(data)
                    print("> ", end="", flush=True)
            
            elif data == "":
                print()
                print("200 status code received.")
                print("> ", end="", flush=True)

            else: 
                print()
                print("200 status code received.")
                print(data)
                print("> ", end="", flush=True)
        
        else: 
            print()
            print("500 status code received.")
            if data != "":
                print(data)
            print("> ", end="", flush=True)



def main(): 
    
    print("Starting client...")

    command = input("> ")

    parts = command.split()

    if len(parts) != 3 or parts[0] != "connect": 
        print("Invalid command. Use: connect <ip> <port>")
        return 
    
    server_ip = parts[1]
    control_port = int(parts[2])

    # Create CONTROL SOCKET

    control_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    control_socket.connect((server_ip, control_port))

    control_socket.sendall(command.encode())

    response = control_socket.recv(1024).decode()

    status_code, data_port = parse_server_response(response) 

    if status_code != "200":
        print("500 status code received. Connection failed")
        control_socket.close()
        return
    
    print(f"200 status code received. Starting data connection on port {data_port}")

    # Create the DATA socket

    data_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM) 

    data_socket.connect((server_ip, int(data_port)))

    listener_thread = threading.Thread(
        target=listen_for_server_messages,
        args=(data_socket,),
        daemon=True
    )

    listener_thread.start()

    # Command loop

    while True: 

        command = input("> ")

        if command.strip() == "":
            continue

        control_socket.sendall(command.encode())

        if command.strip() == "quit":
            time.sleep(0.2)
            break
        
    data_socket.close()
    control_socket.close()


if __name__ == "__main__":
    main()
