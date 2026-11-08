---
title: Rover 2027 — meeting notes
date: 2026-10-04
author: Ishita Rao
---

# Rover 2027 — meeting notes

## 13 Sep: controller

We picked the **ESP32** over the Arduino Mega because it has Wi-Fi built in, and we need
live telemetry during the run. Kunal owns the firmware.

## 27 Sep: navigation

Navigation uses two ultrasonic sensors plus a cheap lidar. The full lidar was too expensive.
Rohan owns the motor control code; Ananya owns the chassis and wiring.

## 4 Oct: battery

The LiPo pack overheated after about 15 minutes in testing. We switched to a Li-ion pack:
heavier, but it stays cool. Ananya to redo the battery mount.

Competition is on **14 Feb 2027**. Registration closes on **1 Dec 2026**.
