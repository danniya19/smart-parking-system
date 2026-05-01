Team Members / Collaborators

Daniya Mehmood 

Zainab RAfique

Smart Parking System with Wrong Parking Detection
A high-fidelity IoT solution that bridges Hardware (Arduino) and Software (Python GUI) to manage parking infrastructure. The system features automated slot allocation, real-time occupancy tracking using Ultrasonic sensors, and an intelligent verification logic to detect unauthorized parking.

 Key Features
Intelligent Allocation: Automatically finds the nearest vacant slot and assigns it via License Plate Number (LPN).

Hardware-Software Sync: Real-time data sync between Arduino sensors and Python dashboard.

Wrong Parking Detection: Instant GUI alerts and LED status changes if a car parks in an unassigned slot.

NewPing Optimization: Uses the NewPing library for stable, noise-free ultrasonic distance readings.

Data Persistence: Complete logging of vehicle entry/exit times in a local SQLite database.

🛠 Tech Stack
Languages: Python 3.x, C++ (Arduino)

Frameworks: Tkinter (GUI), PySerial (Communication)

Database: SQLite3

Hardware: Arduino Uno, 3x HC-SR04 Ultrasonic Sensors, 6x LEDs (Red/Green)

 Project Structure
Plaintext
smart-parking-system/
│
├── main.py               
├── requirements.txt                 
│
├── arduino/
│   └── smart_parking.ino  
│

Installation & Setup
1. Hardware Configuration
Connect your components to the Arduino Uno as per the following pin mapping:

Ultrasonic Sensors:

Slot 1: Trig 2, Echo 3

Slot 2: Trig 4, Echo 5

Slot 3: Trig 6, Echo 7

LEDs:

Slot 1: Green 8, Red 9

Slot 2: Green 10, Red 11

Slot 3: Green 12, Red 13

2. Arduino Firmware
Open arduino/smart_parking.ino in the Arduino IDE.

Go to Sketch > Include Library > Manage Libraries and install NewPing.

Select your Board (Arduino Uno) and Port.

Click Upload.

3. Python Application
Clone the repository or download the files.

Install the required Python library:

Bash
pip install pyserial
Open main.py and ensure the SERIAL_PORT variable matches your Arduino port (e.g., COM8 on Windows).

Run the application:

Bash
python main.py

System Logic Flow
Input: Operator enters the car's LPN in the Python GUI.

Allocation: System finds a vacant slot, updates the DB to waiting, and sends a command to Arduino to turn on the Green LED for that slot.

Verification:

If the car parks in the Correct Slot: Status becomes occupied, LED turns Red.

If the car parks in the Wrong Slot: Python triggers a showwarning alert, and the wrongly occupied slot's Red LED turns on.

Exit: Once the sensor detects a distance > 15cm, the slot is reset to vacant, and the exit time is logged.
