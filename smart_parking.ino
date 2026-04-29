#include <NewPing.h>

const int numSlots = 3;

// Ultrasonic sensor pins (Trig, Echo)
const int trigPins[numSlots] = {2, 4, 6};
const int echoPins[numSlots] = {3, 5, 7};

// Green LED pins
const int greenLeds[numSlots] = {8, 10, 12};

// Red LED pins
const int redLeds[numSlots] = {9, 11, 13};

NewPing sonar[numSlots] = {
  NewPing(trigPins[0], echoPins[0], 200), // Slot 1: Trig, Echo, Max distance (cm)
  NewPing(trigPins[1], echoPins[1], 200), // Slot 2
  NewPing(trigPins[2], echoPins[2], 200)  // Slot 3
};

// Threshold distance (in cm) to consider a slot occupied
const int occupiedThreshold = 15; // Adjust this value based on your model

// Array to store the status of each slot (true=occupied, false=vacant)
bool slotOccupied[numSlots] = {false, false, false};

void setup() {
  Serial.begin(9600);

  for (int i = 0; i < numSlots; i++) {
    pinMode(greenLeds[i], OUTPUT);
    pinMode(redLeds[i], OUTPUT);
    digitalWrite(greenLeds[i], HIGH); // Initially vacant
    digitalWrite(redLeds[i], LOW);
  }
}

void loop() {
  for (int i = 0; i < numSlots; i++) {
    delay(50); // Small delay between sensor readings

    unsigned int distanceCm = sonar[i].ping_cm();

    bool currentOccupied = (distanceCm <= occupiedThreshold && distanceCm > 0); // Object within threshold

    if (currentOccupied != slotOccupied[i]) {
      slotOccupied[i] = currentOccupied;

      Serial.print("Slot");
      Serial.print(i + 1);
      Serial.print(":");
      Serial.print(currentOccupied ? "occupied" : "vacant");
      Serial.print(" ");

      digitalWrite(greenLeds[i], currentOccupied ? LOW : HIGH);
      digitalWrite(redLeds[i], currentOccupied ? HIGH : LOW);
    }
  }
  Serial.println();

  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    processCommand(command);
  }
}

void processCommand(String command) {
  if (command.startsWith("Slot")) {
    int slot = command.substring(4, 5).toInt() - 1;
    String ledCommand = command.substring(6);

    if (slot >= 0 && slot < numSlots) {
      if (ledCommand == "redOn") {
        digitalWrite(redLeds[slot], HIGH);
        digitalWrite(greenLeds[slot], LOW);
      } else if (ledCommand == "greenOn") {
        digitalWrite(redLeds[slot], LOW);
        digitalWrite(greenLeds[slot], HIGH);
      }
    }
  }
}ye tha code mera