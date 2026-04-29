import sqlite3
import serial
import time
from datetime import datetime
import threading
import tkinter as tk
from tkinter import ttk, messagebox

# --- CONFIG ---
SERIAL_PORT = 'COM8'
BAUD_RATE = 9600
DB_PATH = 'parking.db'

# --- INIT SERIAL ---
try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    time.sleep(2) # Give Arduino time to reset
    print(f"✅ Serial port {SERIAL_PORT} initialized.")
except serial.SerialException as e:
    print(f"❌ Serial port error: {e}")
    ser = None # Set ser to None if initialization fails

# --- DB SETUP ---
def create_db_connection():
    """Establishes a connection to the SQLite database."""
    return sqlite3.connect(DB_PATH)

def setup_database():
    """Sets up the necessary tables in the database and initializes parking slots."""
    conn = create_db_connection()
    cur = conn.cursor()
    # Create parking_slots table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS parking_slots (
            slot_id INTEGER PRIMARY KEY,
            status TEXT DEFAULT 'vacant', -- 'vacant', 'waiting', 'occupied'
            lpn TEXT,
            enter_time TEXT
        )
    ''')
    # Create parking_logs table for historical data
    cur.execute('''
        CREATE TABLE IF NOT EXISTS parking_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lpn TEXT,
            slot_id INTEGER,
            enter_time TEXT,
            exit_time TEXT
        )
    ''')
    # Initialize 3 parking slots if they don't already exist
    for i in range(1, 4):
        cur.execute("INSERT OR IGNORE INTO parking_slots (slot_id) VALUES (?)", (i,))
    conn.commit()
    conn.close()

# --- CORE FUNCTIONS ---
def find_next_vacant_slot():
    """Finds the lowest available vacant parking slot ID."""
    conn = create_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT slot_id FROM parking_slots WHERE status = 'vacant' ORDER BY slot_id ASC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None

def assign_slot(lpn, slot_id):
    """Assigns an LPN to a slot and updates its status to 'waiting'."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = create_db_connection()
    cur = conn.cursor()
    # We set the LPN and time for the 'waiting' slot, but don't mark it occupied yet.
    cur.execute("UPDATE parking_slots SET lpn = ?, enter_time = ?, status = 'waiting' WHERE slot_id = ?", (lpn, now, slot_id))
    # Log the entry when assigned (even if 'waiting'). Exit time will be updated on actual exit.
    cur.execute("INSERT INTO parking_logs (lpn, slot_id, enter_time) VALUES (?, ?, ?)", (lpn, slot_id, now))
    conn.commit()
    conn.close()
    print(f"✅ Assigned Slot: {slot_id} for LPN '{lpn}' at {now}. Please park your car.")
    if ser:
        ser.write(f"Slot{slot_id}greenOn\n".encode()) # Instruct Arduino to turn on green light for assigned slot
    refresh_table()

def update_slot_status(slot_id, status, clear_lpn=False):
    """Updates the status of a parking slot in the database."""
    conn = create_db_connection()
    cur = conn.cursor()
    if status == 'vacant' and clear_lpn:
        cur.execute("UPDATE parking_slots SET status = 'vacant', lpn = NULL, enter_time = NULL WHERE slot_id = ?", (slot_id,))
        if ser:
            ser.write(f"Slot{slot_id}allOff\n".encode()) # Turn off all lights when vacant
    else:
        cur.execute("UPDATE parking_slots SET status = ? WHERE slot_id = ?", (status, slot_id))
    conn.commit()
    conn.close()
    refresh_table()

def update_exit_time(slot_id):
    """Records the exit time for a car from a given slot in the parking logs."""
    conn = create_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT lpn FROM parking_slots WHERE slot_id = ?", (slot_id,))
    row = cur.fetchone()
    if row and row[0]:
        lpn = row[0]
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Update the most recent log entry for this LPN and slot that doesn't have an exit_time yet
        cur.execute("UPDATE parking_logs SET exit_time = ? WHERE lpn = ? AND slot_id = ? AND exit_time IS NULL",
                    (now, lpn, slot_id))
        print(f"➡️ Car with LPN '{lpn}' exited from Slot {slot_id} at {now}.")
    conn.commit()
    conn.close()
    refresh_table()

def sensor_listener():
    """
    Listens for serial data from Arduino, processes sensor readings,
    and updates parking slot statuses.
    It actively senses for 1 second, then pauses for 1.5 seconds.
    """
    if not ser:
        print("Serial port not initialized, sensor listener will not run.")
        return

    prev_states = {}  # To keep track of previous sensor states to avoid redundant updates

    while True:
        try:
            # --- Active Sensing Period (1 second) ---
            start_time = time.time()
            while time.time() - start_time < 1.0:  # Loop for approx 1 second
                line = ser.readline().decode().strip()
                if not line:
                    continue  # No data yet, continue reading

                # Process line...
                parts = line.split(" ")
                for part in parts:
                    if not part.startswith("Slot"):
                        continue

                    try:
                        slot_id_str, state = part[4:].split(":")
                        slot_id = int(slot_id_str)

                        if slot_id not in prev_states or prev_states[slot_id] != state:
                            prev_states[slot_id] = state
                            print(f"Detected change: Slot {slot_id} is {state}")
                            if state == "occupied":
                                app.after(0, lambda s=slot_id: handle_occupancy(s))
                            elif state == "vacant":
                                app.after(0, lambda s=slot_id: handle_vacancy(s))
                    except ValueError:
                        print(f"⚠️ Error parsing part '{part}': Invalid format.")
                    except Exception as e:
                        print(f"⚠️ General error processing message part '{part}': {e}")

                time.sleep(0.01)  # Small delay inside active period to yield to other threads/events

            # --- Inactive Period (1.5 seconds) ---
            time.sleep(2)  # Pause for 1.5 seconds after active sensing

        except serial.SerialException as e:
            print(f"❌ Serial communication error (listener thread): {e}")
            break
        except Exception as e:
            print(f"❌ Unexpected error in sensor_listener: {e}")
            break

def handle_occupancy(slot_id):
    """Handles logic when a sensor detects a slot becoming occupied."""
    conn = create_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT status, lpn FROM parking_slots WHERE slot_id = ?", (slot_id,))
    row = cur.fetchone()
    conn.close()

    if row:
        status, lpn_at_slot = row # lpn_at_slot is the LPN currently associated with this slot_id in DB

        if status == "waiting":
            # Car has correctly parked in its assigned slot
            update_slot_status(slot_id, "occupied")
            print(f"✅ Car with LPN '{lpn_at_slot}' parked correctly in Slot {slot_id}.")
            if ser:
                ser.write(f"Slot{slot_id}greenOff\n".encode()) # Turn off green light
        elif status == "vacant":
            # Wrong parking detected: A previously vacant slot is now occupied.
            # This car is either unauthorized or parked in the wrong spot.
            
            message = f"Wrong parking detected: Slot {slot_id} was vacant but is now occupied."
            current_parker_lpn = "UNKNOWN" # We don't know the LPN of the car that just parked here directly

            # Check if there's any LPN currently in 'waiting' status for *any* slot.
            # This helps to identify if a driver made a mistake.
            conn = create_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT lpn, slot_id FROM parking_slots WHERE status = 'waiting'")
            waiting_cars = cur.fetchall()
            conn.close()

            if waiting_cars:
                for waiting_lpn, assigned_slot_id in waiting_cars:
                    if assigned_slot_id != slot_id:
                        # If a waiting car is found, assume this is the one that parked here by mistake.
                        # This is an assumption, as we don't have LPN reader at each slot.
                        current_parker_lpn = waiting_lpn
                        message += (f"\n\nCar with LPN '{current_parker_lpn}' was assigned to Slot {assigned_slot_id} "
                                    f"but seems to have parked in Slot {slot_id} instead.")
                        
                        # Crucial: The assigned slot remains 'waiting'.
                        # The newly occupied slot should be marked as occupied by this LPN.
                        conn = create_db_connection()
                        cur = conn.cursor()
                        # Update the 'wrong' slot to occupied by the found LPN
                        cur.execute("UPDATE parking_slots SET status = 'occupied', lpn = ?, enter_time = ? WHERE slot_id = ?",
                                    (current_parker_lpn, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), slot_id))
                        
                        # Update the log for the LPN to reflect its actual parking slot.
                        # We need to find the latest log entry for this LPN that was assigned to the *other* slot.
                        # This is a bit tricky, if the LPN was assigned multiple times.
                        # A simpler approach might be to just update the 'parking_slots' table and let logs be what they are initially.
                        # For now, let's keep the log entry from 'assign_slot' for the original slot and just update the current 'parking_slots'.
                        
                        conn.commit()
                        conn.close()

                        if ser:
                            # Turn on red for the wrongly occupied slot, turn off green for the original assigned slot.
                            ser.write(f"Slot{slot_id}redOn\n".encode())
                            ser.write(f"Slot{assigned_slot_id}greenOff\n".encode()) # Original slot green off, as car is elsewhere
                        break # Stop after identifying the first relevant waiting car
                else: # No waiting car found that matches the wrong parking scenario
                    message += "\n\nAn unauthorized car has parked here (LPN unknown). Please take action."
                    # Mark the slot as occupied by an unknown LPN
                    update_slot_status(slot_id, "occupied") # Still mark it occupied so it's not re-assigned
                    # Also log this as an "unknown" entry for the occupied slot
                    conn = create_db_connection()
                    cur = conn.cursor()
                    cur.execute("INSERT INTO parking_logs (lpn, slot_id, enter_time) VALUES (?, ?, ?)",
                                ("UNKNOWN", slot_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                    conn.commit()
                    conn.close()
                    if ser:
                        ser.write(f"Slot{slot_id}redOn\n".encode()) # Turn on red light
            else:
                # No cars in 'waiting' status, so it's a completely unauthorized park.
                message += "\n\nAn unauthorized car has parked here (LPN unknown). Please take action."
                update_slot_status(slot_id, "occupied") # Mark it occupied
                # Also log this as an "unknown" entry for the occupied slot
                conn = create_db_connection()
                cur = conn.cursor()
                cur.execute("INSERT INTO parking_logs (lpn, slot_id, enter_time) VALUES (?, ?, ?)",
                            ("UNKNOWN", slot_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                conn.commit()
                conn.close()
                if ser:
                    ser.write(f"Slot{slot_id}redOn\n".encode()) # Turn on red light
            
            app.after(0, lambda: messagebox.showwarning("Wrong Parking Detected!", message, parent=app))
            refresh_table() # Refresh table to reflect changes

        elif status == "occupied":
            print(f"Slot {slot_id} is already occupied (no state change).")

def handle_vacancy(slot_id):
    """Handles logic when a sensor detects a slot becoming vacant."""
    conn = create_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT status, lpn FROM parking_slots WHERE slot_id = ?", (slot_id,))
    row = cur.fetchone()
    conn.close()

    if row:
        status, lpn = row
        if status == "occupied":
            # Car has exited from an occupied slot
            update_exit_time(slot_id)
            update_slot_status(slot_id, "vacant", clear_lpn=True)
            print(f"🟢 Slot {slot_id} became vacant.")
        elif status == "waiting":
            # Car was assigned a slot but left before occupying it (e.g., driver changed mind or parked elsewhere)
            # We assume the car left the premise or decided not to park in that slot.
            # We don't want to clear the LPN from the slot in the 'waiting' state, as the user might want to re-assign or guide them.
            # Instead, just update the status to vacant and clear the LPN ONLY if we consider it a 'cancelled' assignment.
            # For this scenario, let's keep it simple: if a 'waiting' slot becomes vacant, the assignment is effectively cancelled.
            update_slot_status(slot_id, "vacant", clear_lpn=True) # Clear waiting state and LPN
            print(f"⚠️ Slot {slot_id} was waiting for LPN '{lpn}', but became vacant prematurely. Assignment cancelled.")
            if ser:
                ser.write(f"Slot{slot_id}allOff\n".encode()) # Turn off any light that might have been on
            app.after(0, lambda: messagebox.showinfo("Assignment Cancelled", f"LPN '{lpn}' assigned to Slot {slot_id} did not park. Slot is now vacant.", parent=app))
        elif status == "vacant":
            print(f"Slot {slot_id} is already vacant (no state change).")
# --- GUI SETUP ---
app = tk.Tk()
app.title("🚗 Smart Parking System")
app.geometry("700x450") 
style = ttk.Style()
style.theme_use('clam') 


BACKGROUND_COLOR = "#bcded9"   
PRIMARY_COLOR = "#fcd446"      
SECONDARY_COLOR = "#1cac8b"    
TEXT_COLOR = "#3f5a6e"         
ACCENT_COLOR_MUTED = "#7299b2" 
BUTTON_TEXT_COLOR = "#3f5a6e" 
app.configure(bg=BACKGROUND_COLOR)

style.configure('.', font=('Times New Roman', 10), background=BACKGROUND_COLOR, foreground=TEXT_COLOR)


style.configure('Treeview.Heading', font=('Times New Roman', 11, 'bold'), background=PRIMARY_COLOR, foreground=BUTTON_TEXT_COLOR) # Teal heading, dark text
style.configure('Treeview', rowheight=25, fieldbackground=BACKGROUND_COLOR, background=BACKGROUND_COLOR, foreground=TEXT_COLOR)
style.map('Treeview', background=[('selected', SECONDARY_COLOR)]) # Darker green selection


style.configure('TButton', font=('Times New Roman', 10, 'bold'), background=PRIMARY_COLOR, foreground=BUTTON_TEXT_COLOR, padding=8) # Teal buttons, dark text
style.map('TButton', background=[('active', '#0a9a94')]) # Slightly darker teal on hover

style.configure('TEntry', padding=5, font=('Times New Roman', 10), fieldbackground=BACKGROUND_COLOR, foreground=TEXT_COLOR, borderwidth=1, relief="solid") # Darker teal field, light text


tree = ttk.Treeview(app, columns=("Slot", "Status", "LPN", "Enter Time"), show='headings', style='Treeview')
tree.heading("Slot", text="Slot")
tree.heading("Status", text="Status")
tree.heading("LPN", text="License Plate")
tree.heading("Enter Time", text="Enter Time")
tree.column("Slot", width=50, anchor="center")
tree.column("Status", width=100, anchor="center")
tree.column("LPN", width=150, anchor="center")
tree.column("Enter Time", width=180, anchor="center")
tree.pack(fill=tk.BOTH, expand=True, padx=15, pady=15) 

def refresh_table():
    """Refreshes the main parking slots display in the GUI."""
    for item in tree.get_children():
        tree.delete(item)
    conn = create_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT slot_id, status, lpn, enter_time FROM parking_slots ORDER BY slot_id ASC")
    rows = cur.fetchall()
    conn.close()
    for row in rows:
        slot_id, status, lpn, enter_time = row
        # Apply color tagging based on slot status for visual cues
        if status == 'vacant':
            tag = 'vacant'
        elif status == 'occupied':
            tag = 'occupied'
        elif status == 'waiting':
            tag = 'waiting'
        else:
            tag = '' # Default tag if status is unexpected
        tree.insert("", tk.END, values=(slot_id, status, lpn or "---", enter_time or "---"), tags=(tag,))

# Define tags for row coloring in the Treeview (adjusted for new theme)
tree.tag_configure('vacant', background=BACKGROUND_COLOR, foreground=TEXT_COLOR)
tree.tag_configure('occupied', background=SECONDARY_COLOR, foreground='#FFFFFF') # Occupied in darker teal, white text
tree.tag_configure('waiting', background=ACCENT_COLOR_MUTED, foreground='#FFFFFF') # Waiting in muted brown-gray, white text

# --- Allocation Frame ---
frame = ttk.Frame(app, padding=(10, 10), relief="groove", style='DarkFrame.TFrame') # Apply a custom frame style
frame.pack(pady=10)

# Custom frame style for background
style.configure('DarkFrame.TFrame', background=BACKGROUND_COLOR)

tk.Label(frame, text="Enter License Plate Number (LPN):", font=('Times New Roman', 10, 'bold'), background=BACKGROUND_COLOR, foreground=TEXT_COLOR).pack(side=tk.LEFT, padx=10)
lpn_entry = ttk.Entry(frame, width=20, style='TEntry') # Set width and apply style
lpn_entry.pack(side=tk.LEFT, padx=10)

def allocate():
    """Handles the allocation of a parking slot to a new LPN."""
    lpn = lpn_entry.get().strip().upper()
    if not lpn:
        messagebox.showerror("Invalid Input", "Please enter a valid License Plate Number.", parent=app)
        return
    slot = find_next_vacant_slot()
    if not slot:
        messagebox.showwarning("No Vacant Slot", "No vacant slot available!", parent=app)
        return
    assign_slot(lpn, slot)
    lpn_entry.delete(0, tk.END) # Clear the entry field after allocation
    refresh_table()

ttk.Button(frame, text="Allocate Slot", command=allocate, style='TButton').pack(side=tk.LEFT, padx=10)

# --- Logs Window With Search ---
def show_logs():
    """Creates and displays a Toplevel window for parking logs with search functionality."""
    logs_win = tk.Toplevel(app)
    logs_win.title("Parking Logs")
    logs_win.geometry("750x400") # Slightly increased size for logs
    logs_win.configure(bg=BACKGROUND_COLOR)

    search_frame = ttk.Frame(logs_win, padding=(10, 10), style='DarkFrame.TFrame') # Apply custom frame style
    search_frame.pack(pady=10)

    tk.Label(search_frame, text="Search by LPN:", font=('Times New Roman', 10, 'bold'), background=BACKGROUND_COLOR, foreground=BACKGROUND_COLOR).pack(side=tk.LEFT, padx=5)
    search_entry = ttk.Entry(search_frame, width=25, style='TEntry')
    search_entry.pack(side=tk.LEFT, padx=5)

    # Treeview for displaying logs
    logs_tree = ttk.Treeview(logs_win, columns=("ID", "LPN", "Slot", "Enter Time", "Exit Time"), show="headings", style='Treeview')
    logs_tree.heading("ID", text="ID")
    logs_tree.heading("LPN", text="License Plate")
    logs_tree.heading("Slot", text="Slot")
    logs_tree.heading("Enter Time", text="Enter Time")
    logs_tree.heading("Exit Time", text="Exit Time")
    logs_tree.column("ID", width=30, anchor="center")
    logs_tree.column("LPN", width=120, anchor="center")
    logs_tree.column("Slot", width=50, anchor="center")
    logs_tree.column("Enter Time", width=150, anchor="center")
    logs_tree.column("Exit Time", width=150, anchor="center")
    logs_tree.pack(fill=tk.BOTH, expand=True, padx=15, pady=10) # Increased padding

    def fetch_logs(filter_lpn=None):
        """Fetches and displays parking logs, with optional LPN filtering."""
        for item in logs_tree.get_children():
            logs_tree.delete(item) # Clear existing entries
        conn = create_db_connection()
        cur = conn.cursor()
        if filter_lpn:
            cur.execute("SELECT * FROM parking_logs WHERE lpn LIKE ? ORDER BY id DESC", (f"%{filter_lpn}%",))
        else:
            cur.execute("SELECT * FROM parking_logs ORDER BY id DESC")
        rows = cur.fetchall()
        conn.close()
        for row in rows:
            log_id, lpn, slot, et, xt = row
            logs_tree.insert("", tk.END, values=(log_id, lpn, slot, et, xt or "---"))

    def on_search():
        """Callback for the search button in the logs window."""
        filter_lpn = search_entry.get().strip().upper()
        fetch_logs(filter_lpn)

    ttk.Button(search_frame, text="Search", command=on_search, style='TButton').pack(side=tk.LEFT, padx=5)
    ttk.Button(search_frame, text="Reset", command=lambda: fetch_logs(), style='TButton').pack(side=tk.LEFT)

 
    fetch_logs()


ttk.Button(app, text="Show Logs", command=show_logs, style='TButton').pack(pady=10)


if __name__ == "__main__":
    setup_database()
    refresh_table()   
    # Start the sensor listener in a separate daemon thread
  
    threading.Thread(target=sensor_listener, daemon=True).start()
    
    try:
        app.mainloop()
    except KeyboardInterrupt:
        print("\n👋 Exiting application...")
    finally:
       
        if ser and ser.is_open:
            ser.close()
            print("Serial port closed.")