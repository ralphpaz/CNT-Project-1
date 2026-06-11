# CNT Project 1 — Full Code Walkthrough

This project is a multi-user chat program built in Python. One server runs in the background, and multiple clients can connect to it at the same time to send messages to each other. This document explains every function and every design choice in plain language.

---

## Table of Contents

1. [Big Picture: How It Works](#1-big-picture-how-it-works)
2. [The Message Format](#2-the-message-format)
3. [Why There Are Two Connections Per Client](#3-why-there-are-two-connections-per-client)
4. [server.py — Every Function Explained](#4-serverpy--every-function-explained)
5. [client.py — Every Function Explained](#5-clientpy--every-function-explained)
6. [A Full Session, Step by Step](#6-a-full-session-step-by-step)
7. [How Threads Work in This Project](#7-how-threads-work-in-this-project)
8. [Every Command and What Happens](#8-every-command-and-what-happens)
9. [Shared Data and Preventing Bugs with Locks](#9-shared-data-and-preventing-bugs-with-locks)
10. [Setup & How to Run](#10-setup--how-to-run)
11. [Known Limitations](#11-known-limitations)

---

## 1. Big Picture: How It Works

There is one server and potentially many clients. Think of the server like a post office — it receives messages from everyone and routes them to the right people. Each client is a user at their own computer typing commands into a terminal.

Each client has **two separate connections** to the server. One connection is used to send commands (like "login" or "broadcast"). The other connection is used to receive responses and incoming messages. This separation is explained in detail in Section 3.

```
┌─────────────────────────────────────────────────────────────────────┐
│                            SERVER                                   │
│                                                                     │
│   Main port (e.g. 5000) — new clients connect here first           │
│   │                                                                 │
│   │  waits for new clients                                          │
│   │                                                                 │
│   ├── Client A (alice) ───────────────────────────────────────┐    │
│   │    her thread: handle_new_client → handle_client_commands  │    │
│   │    her private response port (e.g. 54321)                  │    │
│   │                                                            │    │
│   ├── Client B (bob) ────────────────────────────────────────┐ │    │
│   │    his thread: handle_new_client → handle_client_commands │ │    │
│   │    his private response port (e.g. 54322)                 │ │    │
│   │                                                           │ │    │
│   └── ...more clients...                                      │ │    │
│                                                               │ │    │
│   active_clients = {                                          │ │    │
│     "alice": { command_socket: ..., response_socket: ─────────┘ │    │
│     "bob":   { command_socket: ..., response_socket: ───────────┘    │
│   }                                                                 │
└─────────────────────────────────────────────────────────────────────┘

         ▲  commands go UP   (login, who, broadcast...)
         │  responses go DOWN (200 OK, error messages, chat messages)
         ▼

┌──────────────────────────────┐
│           CLIENT             │
│                              │
│  Main thread                 │
│  └─ reads what you type      │
│  └─ sends commands to server │
│                              │
│  Background listener thread  │
│  └─ waits for server messages│
│  └─ prints them when they    │
│     arrive                   │
└──────────────────────────────┘
```

---

## 2. The Message Format

Every message sent between the client and server — in either direction — uses the same simple format:

```
<status_code>\n\n<data>
```

- `<status_code>` is either `200` (everything worked) or `500` (something went wrong)
- `\n\n` is two newline characters back-to-back — this acts as the divider between the status and the actual content
- `<data>` is optional extra text (it can be empty)

This is similar in spirit to how HTTP works — you get a status code and then content. `200` means success (just like HTTP 200 OK), and `500` means error.

### Examples of real messages on the wire

A plain success with no extra information:
```
200\n\n
```

A success that includes a port number (sent during connection setup):
```
200\n\n54321
```

An error with an explanation:
```
500\n\nUsername already taken
```

A broadcast message being pushed to all clients:
```
200\n\nBroadcast\nalice\nhello everyone
```

A private message being pushed to one recipient:
```
200\n\nPrivate\nalice\nhey only you
```

A logout notice being pushed to everyone still connected:
```
200\n\nLogout\nalice
```

### How messages that get pushed to clients are structured

For messages the server sends out on its own (not in direct reply to a command), the `<data>` section uses `\n` to separate multiple pieces of information:

```
Broadcast\n<who sent it>\n<the message text>
Private\n<who sent it>\n<the message text>
Logout\n<username of who left>
```

The first word (`Broadcast`, `Private`, or `Logout`) tells the client what kind of message it is. The client then splits on `\n` to get the individual pieces.

---

## 3. Why There Are Two Connections Per Client

This is the most important design concept in the whole project. Each client opens **two separate TCP connections** to the server.

A **TCP connection** is like a phone call between two programs — once it's open, both sides can send and receive data through it. A **port** is like an extension number — it lets the server tell apart different connections coming from different clients.

Here is why two connections are needed:

> Imagine you only had one connection. The client would use it to both send commands AND receive messages. The problem is that `recv()` (the function that reads data from a socket) **blocks** — it freezes your program until data arrives. If the client is sitting in `recv()` waiting for an incoming broadcast message, it cannot read from the keyboard at the same time. The user would be stuck.

Two connections solve this by splitting the work: one connection is dedicated to sending commands (so the user can always type), and the other is listened to by a background thread (so incoming messages are printed automatically without blocking anything).

```
PHASE 1 — The client first connects and gets assigned a private response port
───────────────────────────────────────────────────────────────────────────────

CLIENT                                SERVER
  │                                     │
  │── connects to port 5000 ───────────▶ main port (5000)
  │                                     │
  │── sends "connect 127.0.0.1 5000" ──▶ handle_new_client() runs
  │                                     │
  │                                     │ creates a brand new socket
  │                                     │ on a random free port (e.g. 54321)
  │                                     │
  │◀─ "200\n\n54321" ──────────────────│  "here's your private port"
  │                                     │
  │── connects to port 54321 ──────────▶ response socket (54321)
  │                                     │
  │                           data connection accepted ✓
  │
PHASE 2 — All commands and responses from here on
───────────────────────────────────────────────────────────────────────────────

CLIENT                                SERVER
  │                                     │
  │── "login alice" ───────────────────▶ command socket   (client → server)
  │                                     │
  │◀─ "200\n\n" ───────────────────────│ response socket  (server → client)
  │                                     │
  │── "broadcast hello" ───────────────▶ command socket
  │                                     │
  │◀─ "200\n\nBroadcast\nalice\nhello" ─│ response socket  (sent to all clients)
```

The server **only reads** from the command socket. It **only writes** to the response socket. Commands go one way, responses go the other.

---

## 4. server.py — Every Function Explained

### `format_response(status_code, data="")`

**What it does:** Takes a status code and optional message text, and combines them into the message format the server uses for all replies.

```python
def format_response(status_code, data=""):
    if data == "":
        return f"{status_code}\n\n"
    else:
        return f"{status_code}\n\n{data}"
```

This is a helper function called everywhere in the server. Instead of manually writing `"200\n\n"` or `"500\n\nSome error"` over and over, every part of the server calls this one function.

The `data=""` in the function signature means `data` is optional — if you don't pass it, it defaults to an empty string, and the function just returns the status code with a double newline.

**What it returns in practice:**

| What you call | What you get back |
|---|---|
| `format_response(200)` | `"200\n\n"` |
| `format_response(200, "54321")` | `"200\n\n54321"` |
| `format_response(500, "Username already taken")` | `"500\n\nUsername already taken"` |

Every single `sendall()` call in the server wraps its data through this function first.

---

### `create_data_socket()`

**What it does:** Creates a brand new TCP socket that listens on a random available port. This becomes the private response channel for one specific client.

```python
def create_data_socket():
    data_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    data_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    data_socket.bind(("", 0))
    data_socket.listen()
    data_port = data_socket.getsockname()[1]
    return data_socket, data_port
```

**Line by line:**

```python
socket.socket(socket.AF_INET, socket.SOCK_STREAM)
```
Creates a new socket. `AF_INET` means "use IPv4 addresses" (the standard `x.x.x.x` format). `SOCK_STREAM` means "use TCP" — a reliable connection where data arrives in order and nothing gets dropped. The alternative would be `SOCK_DGRAM` for UDP, which is faster but unreliable.

```python
data_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
```
This is a safety setting. When a connection is closed, the operating system holds the port in a "cooldown" state for a short time before making it available again. Without this line, if you restart the server quickly, it would crash with an "Address already in use" error. This line tells the OS to skip the cooldown and reuse the port immediately.

```python
data_socket.bind(("", 0))
```
"Binding" a socket means telling it which port to use. The `""` means "accept connections on any network interface" (not just one specific IP). The `0` is special — it means "I don't care which port, just pick one that's free." The OS will pick an available port and assign it.

```python
data_socket.listen()
```
Puts the socket into "listening" mode, meaning it is now ready to accept an incoming connection.

```python
data_port = data_socket.getsockname()[1]
```
After the OS picks a port, this asks the socket "what port did you end up on?" `getsockname()` returns a tuple of `(ip_address, port_number)`, so `[1]` gets just the port number. This port number gets sent back to the client so it knows where to connect.

**What it returns:** The socket object itself, and the port number as a plain integer.

---

### `handle_login(parts, client_control_socket, client_data_socket, active_clients, clients_lock, current_username)`

**What it does:** Handles the `login <username>` command. Checks if the username is available and, if so, registers the user.

```python
def handle_login(parts, client_control_socket, client_data_socket,
                 active_clients, clients_lock, current_username):
    if len(parts) != 2:
        response = format_response(500, "Invalid login command")
        client_data_socket.sendall(response.encode())
        return current_username

    requested_username = parts[1]

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
```

**How the logic flows:**

```
Received "login alice"
        │
        ▼
Does the command have exactly 2 words?  ──No──▶ send 500 "Invalid login command"
        │                                        return (username stays None)
       Yes
        │
        ▼
Is this client already logged in?  ──Yes──▶ send 500 "User already logged in"
        │                                    return (username stays the same)
        No
        │
        ▼
Lock the shared dictionary (so no other thread interferes)
        │
        ▼
Is "alice" already in active_clients?  ──Yes──▶ send 500 "Username already taken"
        │                                        release lock, return
        No
        │
        ▼
Add "alice" to active_clients with her sockets
Release the lock
        │
        ▼
Send 200 (success)
Return "alice" — caller now knows this client is logged in as alice
```

**Why the function returns the username:**
The function is called from `handle_client_commands`, which has a variable called `current_username`. By returning the new username on success (or the unchanged one on failure), the caller can just write `current_username = handle_login(...)` and the variable updates automatically. If login fails, nothing changes.

**Why the lock wraps both the check and the insert together:**
Imagine two people tried to claim the same username at the exact same moment. Without a lock, both threads could check "is alice taken?" at the same time, both see "no", and both add "alice" — now there are two users named alice and the second one's entry overwrote the first. This is called a **race condition**. The lock forces the threads to take turns — one finishes completely before the other starts.

---

### `handle_client_commands(client_control_socket, client_data_socket, active_clients, clients_lock)`

**What it does:** This is the main loop that runs for the entire time a client is connected. It continuously waits for commands, figures out what command was sent, and runs the right code for it.

```python
def handle_client_commands(client_control_socket, client_data_socket,
                            active_clients, clients_lock):
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

        if command_name == "login":       # → calls handle_login()
        elif command_name == "who":       # → sends list of users
        elif command_name == "broadcast": # → sends to everyone
        elif command_name == "private":   # → sends to one person
        elif command_name == "quit":      # → disconnects
        else:
            response = format_response(500, "Unknown command")
            client_data_socket.sendall(response.encode())

    # When the loop ends, clean up
    if current_username is not None:
        with clients_lock:
            if current_username in active_clients:
                del active_clients[current_username]
```

**`current_username = None`**
Every client starts as "not logged in." Commands that require a login (like `who`, `broadcast`, etc.) check `if current_username is None` and send back a 500 error if the user hasn't logged in yet.

**`recv(1024).decode().strip()`**
Breaking this down:
- `recv(1024)` — reads up to 1024 bytes from the socket. This call **blocks** — the thread just sits here waiting until the client sends something.
- `.decode()` — sockets work with raw bytes (like `b"login alice"`). `.decode()` turns those bytes into a regular Python string (`"login alice"`).
- `.strip()` — removes any extra spaces or newline characters from the start and end of the string, just in case the client accidentally sent them.

**`except ConnectionResetError: break`**
If the client's program crashes or is force-closed, the operating system sends a signal called a TCP RST (reset). Python sees this as a `ConnectionResetError`. Catching it and calling `break` exits the loop cleanly so this thread can finish.

**`if command == "": break`**
When a TCP connection is closed normally (not by a crash), `recv()` returns empty bytes `b""`, which becomes the empty string `""` after `.decode()`. This is the standard signal that the other side has disconnected. `break` exits the loop.

**Cleanup after the loop:**
No matter why the loop exits — the user typed `quit`, the connection dropped, or an exception occurred — if the user was logged in, they get removed from `active_clients`. Without this, a disconnected user would stay in the list forever and block that username from being reused.

---

**The `who` branch:**

```python
elif command_name == "who":
    if current_username is None:
        response = format_response(500, "You must login first")
    else:
        with clients_lock:
            users = ", ".join(active_clients.keys())
        response = format_response(200, users)
    client_data_socket.sendall(response.encode())
```

`active_clients.keys()` gives all the usernames currently logged in. `", ".join(...)` turns that list into a single string like `"alice, bob, carol"`. The lock is held while reading the keys to make sure no other thread adds or removes a user in the middle of building that string.

---

**The `broadcast` branch:**

```python
elif command_name == "broadcast":
    if current_username is None: # ... error
    elif len(parts) < 2:         # ... error
    else:
        message = " ".join(parts[1:])
        broadcast_data = f"Broadcast\n{current_username}\n{message}"
        response = format_response(200, broadcast_data)

        with clients_lock:
            recipient_sockets = [
                client_info["data_socket"]
                for client_info in active_clients.values()
            ]

        for recipient_socket in recipient_sockets:
            recipient_socket.sendall(response.encode())
```

`" ".join(parts[1:])` rebuilds the message text. For example, if the command was `broadcast hello world`, then `parts` is `["broadcast", "hello", "world"]`. `parts[1:]` is `["hello", "world"]`, and joining with spaces gives `"hello world"`.

Notice the lock is used to **get the list of sockets**, but the actual sending happens **after** releasing the lock. This is intentional — sending data over a network can take a moment, and holding the lock during that time would make every other thread wait. Instead, we grab what we need quickly (the list of sockets), release the lock, then do the slower work of sending.

---

**The `private` branch:**

```python
elif command_name == "private":
    if current_username is None: # ... error
    elif len(parts) < 3:         # ... error
    else:
        recipient_username = parts[1]
        message = " ".join(parts[2:])

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
```

Two separate messages get sent: the full message goes to the recipient, and a plain `200` confirmation goes back to the sender. The sender does **not** receive a copy of their own private message.

---

**The `quit` branch:**

```python
elif command_name == "quit":
    if current_username is not None:
        with clients_lock:
            if current_username in active_clients:
                del active_clients[current_username]    # remove them first
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
        response = format_response(200)
        client_data_socket.sendall(response.encode())

    break
```

The user is removed from `active_clients` **before** the remaining sockets are collected. This way, the quitting user is not in the list when we build the "who to notify" list, so they won't receive their own departure notice.

The `try/except OSError` around each `sendall` is a safety net — it's possible that another client disconnected between when we grabbed their socket and when we tried to write to it. If that happens, `sendall` would throw an error. The `except` catches it silently so one bad socket doesn't stop the server from notifying everyone else.

`break` at the end exits the `while True` loop, which ends this thread's work.

---

### `handle_new_client(client_control_socket, client_address, active_clients, clients_lock)`

**What it does:** This is the starting point for every new client thread. It handles the initial handshake — waiting for the `connect` command, creating the response socket, and then handing off to `handle_client_commands` for all future commands.

```python
def handle_new_client(client_control_socket, client_address,
                      active_clients, clients_lock):
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
```

**Step by step:**

1. Wait for the first message — it must be `connect <ip> <port>`.
2. If it is, call `create_data_socket()` to make a new socket on a random port.
3. Send that port number back to the client.
4. Call `data_socket.accept()` — this **blocks** and waits for the client to open its second connection to that port.
5. Once connected, hand off to `handle_client_commands()` which runs the main command loop.
6. The `finally` block runs no matter what happens — whether the function returns normally, the connection drops, or an exception occurs. It closes all three sockets so the OS can free up those resources. `finally` blocks always run, which is why they are used for cleanup code.

---

### `main()` in server.py

**What it does:** The very first code that runs. It reads the port number from the command line, creates the main listening socket, and loops forever accepting new clients.

```python
def main():
    if len(sys.argv) != 2:
        print("Usage: python server.py <port>")
        return

    control_port = int(sys.argv[1])

    active_clients = {}
    clients_lock = threading.Lock()

    control_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    control_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    control_socket.bind(("", control_port))
    control_socket.listen()

    while True:
        client_control_socket, client_address = control_socket.accept()

        client_thread = threading.Thread(
            target=handle_new_client,
            args=(client_control_socket, client_address, active_clients, clients_lock)
        )
        client_thread.start()
```

**`sys.argv`** is a list of everything you typed on the command line. `sys.argv[0]` is always the script name itself (`server.py`). `sys.argv[1]` is the first argument you provided — the port number. If you forget to provide a port, `len(sys.argv)` will be 1, not 2, and the server prints the usage message and exits.

**`active_clients = {}`** is created here once and passed into every client thread. All threads share this same dictionary object. This is the shared "who is online" list. The lock protects it from being read and written at the same time by different threads.

**`control_socket.accept()`** pauses and waits until a new client connects. When one does, it returns a new socket specifically for that client, plus the client's address. The main loop immediately creates a new thread to handle that client and goes right back to `accept()` to wait for the next one. This is how the server handles many clients at the same time.

**`threading.Thread(...).start()`** creates and starts a new thread. A **thread** is like a separate worker that runs concurrently with everything else. Each client gets their own thread. The `target` is the function the thread will run, and `args` are the arguments passed to it.

---

## 5. client.py — Every Function Explained

### `parse_server_response(response)`

**What it does:** Takes a raw string received from the server and splits it into two parts — the status code and the data.

```python
def parse_server_response(response):
    parts = response.split("\n\n", 1)
    status_code = parts[0].strip()

    if len(parts) > 1:
        data = parts[1].strip()
    else:
        data = ""

    return status_code, data
```

**`response.split("\n\n", 1)`**
The `1` tells Python to split at most once. So if the response is `"200\n\nBroadcast\nalice\nhello"`, it becomes `["200", "Broadcast\nalice\nhello"]`. Without the `1`, Python would split at every `\n\n`, which could accidentally chop up message content.

**`parts[0].strip()`**
Cleans up the status code by removing any extra whitespace around it. This makes comparing it with `== "200"` safe even if there is a stray space somewhere.

**`if len(parts) > 1`**
If the server sent a message with no `\n\n` at all (which shouldn't happen but is possible if something went wrong), `split` would return a list with just one item. Trying to access `parts[1]` would crash with an `IndexError`. This check handles that case gracefully.

---

### `print_response_for_command(command, status_code, data)`

**What it does:** Prints the server's response to a command the user just typed. The exact message printed depends on which command was sent.

```python
def print_response_for_command(command, status_code, data):
    command_parts = command.split()

    if len(command_parts) == 0:
        return

    command_name = command_parts[0]

    if status_code == "200":
        if command_name == "login":
            print("200 status code received. Login successful")
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
```

This function is called from `main()` right after the user types a command and the server responds. It looks at which command was sent to decide the right thing to print — for example, `login` gets "Login successful" but `who` prints the list of users.

**Important:** This function only handles responses to commands **you** typed. If someone else sends you a broadcast or private message, those arrive on the data socket and are handled by `listen_for_server_messages` instead (see below).

---

### `listen_for_server_messages(data_socket)`

**What it does:** Runs in the background thread. It sits in a loop waiting for messages from the server and prints them when they arrive — things like incoming chat messages and departure notifications.

```python
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

            elif data.startswith("Private\n"):
                lines = data.split("\n", 2)
                if len(lines) == 3:
                    sender = lines[1]
                    message = lines[2]
                    print()
                    print("200 status code received.")
                    print(f"{sender}: {message}")
                    print("> ", end="", flush=True)

            elif data.startswith("Logout\n"):
                lines = data.split("\n", 1)
                if len(lines) == 2:
                    username = lines[1]
                    print()
                    print("200 status code received.")
                    print(f"{username} left the chat")
                    print("> ", end="", flush=True)
```

**`data.startswith("Broadcast\n")`**
Checks what type of pushed message this is. `startswith` is used instead of `==` because there is more text after the tag (`Broadcast`, `Private`, or `Logout`).

**`data.split("\n", 2)`**
Splits the data into at most 3 pieces: `["Broadcast", "alice", "hello everyone"]`. The `2` limit matters because the message itself might contain newline characters — limiting the split to 2 prevents the message text from being cut apart.

**`print("> ", end="", flush=True)`**
After printing a received message, this re-draws the input prompt on the screen so the user knows they can still type. `end=""` stops Python from adding a newline after the prompt (we want it to stay on the same line). `flush=True` forces Python to display it immediately — by default, Python collects output and sends it to the screen in batches, which would cause the prompt to appear delayed.

**`print()`** by itself prints a blank line before the incoming message. This moves the cursor down so the message does not appear mixed in with whatever the user was typing.

---

### `main()` in client.py

**What it does:** The starting point of the client. It connects to the server, sets up both sockets, starts the background listener thread, and then runs the loop where the user types commands.

```python
def main():
    print("Starting client...")

    command = input("> ")
    parts = command.split()

    if len(parts) != 3 or parts[0] != "connect":
        print("Invalid command. Use: connect <ip> <port>")
        return

    server_ip = parts[1]
    control_port = int(parts[2])

    # Open the command socket
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

    # Open the response socket
    data_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    data_socket.connect((server_ip, int(data_port)))

    listener_thread = threading.Thread(
        target=listen_for_server_messages,
        args=(data_socket,),
        daemon=True
    )
    listener_thread.start()

    # Main command loop
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
```

**`command.encode()`**
Sockets send and receive raw bytes, not Python strings. `.encode()` converts a string like `"login alice"` into bytes like `b"login alice"`. On the server side, `.decode()` converts it back.

**`sendall()` vs `send()`**
`send()` might not send your entire message in one go — it can send only part of it and return how many bytes it actually sent. `sendall()` automatically handles this by retrying until every byte has been sent. Always use `sendall()` when sending a complete message.

**`daemon=True`**
When the main thread finishes (after `quit`), Python normally waits for all other threads to finish before closing the program. But the listener thread is stuck in `recv()` forever. Setting `daemon=True` tells Python: "when the main thread ends, kill this thread automatically." Without it, the program would hang forever after quitting.

**`time.sleep(0.2)`**
After sending `quit`, the client waits 200 milliseconds before closing the sockets. This gives the server time to process the quit, send a `200` response back, and send logout notices to other clients. If the client closed the socket immediately, the server might be mid-way through that process and fail.

**The command loop:**
The loop reads a command, sends it, and immediately goes back to waiting for the next input. It does **not** wait for a response — the response arrives on the data socket and is printed by the listener thread, which is running in parallel. The only exception is `quit`, which breaks out of the loop and closes everything.

---

## 6. A Full Session, Step by Step

```
CLIENT                              SERVER
  │                                   │
  │  python client.py                 │  python server.py 5000
  │  type: connect 127.0.0.1 5000     │
  │                                   │
  │──[opens TCP connection]─────────▶  │  accept() unblocks
  │                                   │  → spawns new thread for this client
  │── "connect 127.0.0.1 5000" ─────▶ │
  │                                   │  create_data_socket() → picks port 54321
  │◀─ "200\n\n54321" ───────────────  │
  │                                   │  now waiting for client on port 54321
  │──[opens TCP connection to 54321]─▶ │  accept() unblocks
  │                                   │
  │  starts listener thread           │  enters handle_client_commands()
  │                                   │
  │── "login alice" ────────────────▶  │  adds "alice" to active_clients
  │◀─ "200\n\n" ─────────────────────  │
  │                                   │
  │── "who" ────────────────────────▶  │  joins all keys from active_clients
  │◀─ "200\n\nalice, bob" ───────────  │
  │                                   │
  │── "broadcast hello" ────────────▶  │  sends to ALL clients' response sockets
  │◀─ "200\n\nBroadcast\nalice\nhello" │  (alice gets her own broadcast back too)
  │  (listener thread prints this)    │
  │                                   │
  │── "private bob hey" ────────────▶  │  sends message to bob's response socket
  │◀─ "200\n\n" ─────────────────────  │  sends plain 200 back to alice
  │                                   │
  │── "quit" ───────────────────────▶  │  removes alice from active_clients
  │◀─ "200\n\n" ─────────────────────  │  sends "Logout\nalice" to everyone else
  │  sleep 200ms                      │
  │  close sockets                    │  closes sockets in finally block
```

---

## 7. How Threads Work in This Project

A **thread** is a way to run multiple pieces of code at the same time inside one program. Think of threads like workers — you can have one worker waiting for user input while another worker is watching for incoming messages.

### Server threads

```
Main thread (runs forever)
└── Waits at control_socket.accept()
    │
    ├── Client A connects → Thread A created and started
    │     runs: handle_new_client(A)
    │     └── runs: handle_client_commands(A)  ← waits here for A's commands
    │
    ├── Client B connects → Thread B created and started
    │     runs: handle_new_client(B)
    │     └── runs: handle_client_commands(B)  ← waits here for B's commands
    │
    └── Client C connects → Thread C created...
```

The main thread never gets stuck — it immediately passes each client off to a new thread and goes back to waiting for the next one. Each client thread runs independently. They all share `active_clients` and `clients_lock`.

### Client threads

```
Main thread
└── opens both sockets
└── starts listener thread
└── loops: reads input → sends command
    │
    Listener thread (daemon)
    └── loops: waits on data socket → prints messages when they arrive
```

These two threads run at the same time. The main thread can sit at `input()` waiting for you to type, and the listener thread can receive and print a broadcast message without interfering.

### Why `daemon=True` matters

```
Without daemon=True:
  User types "quit"
  main() closes the sockets and exits
  Python: "I'll wait for the listener thread to finish..."
  Listener thread: stuck waiting on a now-closed socket
  → the program never exits — it hangs forever

With daemon=True:
  User types "quit"
  main() closes the sockets and exits
  Python: automatically kills daemon threads
  → the program exits cleanly
```

---

## 8. Every Command and What Happens

### `connect <ip> <port>`

The very first command. Handled separately by `handle_new_client`, not by the main command loop.

```
CLIENT sends:    "connect 127.0.0.1 5000"   (over the command socket)
SERVER responds: "200\n\n54321"              (the assigned response port)
CLIENT action:   opens a second socket to port 54321
```

---

### `login <username>`

```
CLIENT sends:   "login alice"

SERVER checks:
  ┌─ is the command exactly 2 words? ──No──▶  "500\n\nInvalid login command"
  │
  ├─ already logged in?  ────────────Yes──▶  "500\n\nUser already logged in"
  │
  └─ username already taken? ────────Yes──▶  "500\n\nUsername already taken"
       │
       No ──▶ add to active_clients ──▶  "200\n\n"

SERVER responds: "200\n\n"              (success)
             or  "500\n\n<reason>"      (failure)
```

---

### `who`

```
CLIENT sends:   "who"

SERVER checks:
  ┌─ not logged in? ──▶ "500\n\nYou must login first"
  └─ logged in?     ──▶ collects all usernames from active_clients
                        "200\n\nalice, bob, carol"

SERVER responds: "200\n\nalice, bob, carol"
```

---

### `broadcast <message>`

```
CLIENT sends:   "broadcast hello everyone"

SERVER checks:
  ┌─ not logged in? ──▶ "500\n\nYou must login first"
  ├─ no message?    ──▶ "500\n\nInvalid broadcast command"
  └─ valid          ──▶ builds the payload and sends to everyone

Payload:       "Broadcast\nalice\nhello everyone"
Full message:  "200\n\nBroadcast\nalice\nhello everyone"

SERVER sends this to: every client in active_clients (including alice herself)

How the listener thread handles it on each client:
  data = "Broadcast\nalice\nhello everyone"
  data.split("\n", 2) = ["Broadcast", "alice", "hello everyone"]
  prints: "Broadcast message from alice: hello everyone"
```

---

### `private <username> <message>`

```
CLIENT sends:   "private bob hey only you"

SERVER checks:
  ┌─ not logged in?  ──▶ "500\n\nYou must login first"
  ├─ missing args?   ──▶ "500\n\nInvalid private command"
  ├─ bob not online? ──▶ "500\n\nUser does not exist"
  └─ bob online?     ──▶ send message to bob, send confirmation to alice

SERVER sends to bob:   "200\n\nPrivate\nalice\nhey only you"
SERVER sends to alice: "200\n\n"   (just a confirmation that it was sent)

Bob's listener thread:
  data = "Private\nalice\nhey only you"
  data.split("\n", 2) = ["Private", "alice", "hey only you"]
  prints: "alice: hey only you"
```

---

### `quit`

```
CLIENT sends:   "quit"

If logged in:
  1. remove user from active_clients
  2. capture remaining clients' sockets
  3. send "200\n\n" to the quitting client
  4. send "200\n\nLogout\nalice" to everyone still connected

If not logged in:
  1. just send "200\n\n"

Remaining clients' listener thread:
  data = "Logout\nalice"
  data.split("\n", 1) = ["Logout", "alice"]
  prints: "alice left the chat"
```

---

## 9. Shared Data and Preventing Bugs with Locks

The `active_clients` dictionary is the only data that multiple threads share. Its structure looks like this:

```python
active_clients = {
    "alice": {
        "control_socket": <socket object>,  # her command socket
        "data_socket":    <socket object>   # her response socket
    },
    "bob": {
        "control_socket": <socket object>,
        "data_socket":    <socket object>
    }
}
```

`clients_lock` is a `threading.Lock()`. A lock works like a bathroom key at a gas station — only one person can hold it at a time. Any thread that wants to read or write `active_clients` must first acquire the lock with `with clients_lock:`. When that block finishes, the lock is released automatically.

### What goes wrong without a lock — a race condition

```
Scenario: Two clients try to pick the same username "alice" at the same time

Thread A (alice's client)         Thread B (also tries "alice")
─────────────────────────         ──────────────────────────────
check: "alice" in dict? → False
                                  check: "alice" in dict? → False
                                                         ↑ Both passed! Bug.
add "alice" to dict
                                  add "alice" to dict  ← overwrites Thread A's entry

Both clients think they logged in as "alice" — but only one entry exists.
Thread A's sockets are now lost. All messages meant for "alice" go to Thread B.
```

With the lock:
```
Thread A acquires the lock
Thread A checks: "alice" in dict? → False
Thread A adds "alice"
Thread A releases the lock
                                  Thread B acquires the lock (was waiting)
                                  Thread B checks: "alice" in dict? → True
                                  Thread B sends 500 "Username already taken"
                                  Thread B releases the lock
```

### Why sending is done outside the lock

Throughout the server, you will see this pattern:

```python
# Step 1: get what we need (inside the lock — fast)
with clients_lock:
    recipient_sockets = [info["data_socket"] for info in active_clients.values()]

# Step 2: do the sending (outside the lock — can be slow)
for sock in recipient_sockets:
    sock.sendall(data)
```

Sending data over a network is not instant. If the lock were held during all the `sendall()` calls, every other thread would be stuck waiting the entire time anyone was broadcasting a message. Grabbing just the socket references quickly (inside the lock) and then sending outside the lock keeps things fast.

---

## 10. Setup & How to Run

### What you need

- Python 3 — download from [python.org/downloads](https://www.python.org/downloads/)
- No extra libraries needed. All imports (`socket`, `threading`, `sys`, `time`) come with Python.

### Start the server

Open a terminal and run:
```bash
python server.py 5000
```

You can use any port number above 1024 (numbers below that are reserved by the OS). The server will print `Awaiting connections...` and wait. Leave this terminal open.

### Start a client

Open a separate terminal window (one per user) and run:
```bash
python client.py
```

Then type:
```
> connect 127.0.0.1 5000
```

`127.0.0.1` is the loopback address — it means "this same machine." If the server is running on a different computer, replace this with that computer's IP address.

### Full example across three terminals

**Terminal 1 — server:**
```
python server.py 5000
Starting server...
Creating server socket
Awaiting connections...
Connection requested. Creating data socket
Data connection established with: ('127.0.0.1', 54889)
Login requested by: alice
Login requested by: bob
Who requested. Sending users.
Broadcast requested by alice
Message: hello everyone
Private message from alice to bob
```

**Terminal 2 — alice:**
```
python client.py
Starting client...
> connect 127.0.0.1 5000
200 status code received. Starting data connection on port 54321
> login alice
200 status code received. Login successful
> who
200 status code received. Users currently connected: alice, bob
> broadcast hello everyone
200 status code received
> private bob hey
200 status code received. Message sent.
> quit
200 status code received
```

**Terminal 3 — bob (sees alice's messages arrive automatically):**
```
python client.py
Starting client...
> connect 127.0.0.1 5000
200 status code received. Starting data connection on port 54322
> login bob
200 status code received. Login successful
>
200 status code received.
Broadcast message from alice: hello everyone
>
200 status code received.
alice: hey
>
200 status code received.
alice left the chat
```

---

## 11. Known Limitations

**Messages can be cut off if they're too long**
`recv(1024)` reads at most 1024 bytes at a time. TCP is a streaming protocol — it doesn't know where one message ends and another begins. If a message is longer than 1024 bytes, it arrives in multiple pieces and the code has no logic to put them back together. Short messages (which is all this program sends) work fine.

**You see your own broadcasts**
When you broadcast a message, the server sends it to every person in `active_clients` — including you. So your own broadcast message will appear on your screen as an incoming message from yourself.

**No passwords**
Anyone can claim any available username. There is no way to verify that you are who you say you are.

**The `time.sleep(0.2)` after quit is not reliable**
After sending `quit`, the client sleeps 200ms to give the server time to respond. On a slow connection this might not be enough. On a fast machine it's just unnecessary waiting. A better solution would be to wait until the `200` response actually arrives before closing the socket.

**No way to shut down the server gracefully**
There is no `shutdown` command. Pressing Ctrl+C kills the process immediately, which drops all connections without warning. Clients will see their sockets suddenly go silent.

**Responses print out of order**
The client sends a command and immediately goes back to waiting for more input — it does not wait for the response. The response arrives on the data socket and gets printed by the listener thread whenever it arrives. On a slow connection, you might type your next command before the previous response appears on screen.
