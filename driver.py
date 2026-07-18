import usb
from threading import Thread
from evdev import UInput, ecodes, AbsInfo
import time

class Driver():
  def __init__(self):
    self.injection_active = True
    self.connection_active = False

    self.settings = {
      "xinput_name": "10moons-pen",
      "vendor_id": "0x08f2",
      "product_id": "0x6811",
      "pen": {
        "max_x": 4096,
        "max_y": 4096,
        "max_pressure": 2047,
        "resolution_x": 20,
        "resolution_y": 30
      },
      "actions": {
        "pen": "BTN_TOOL_PEN",
        "stylus": "BTN_STYLUS",
        "pen_touch": "BTN_TOUCH",
        "pen_buttons": [
          "KEY_LEFTBRACE",
          "KEY_RIGHTBRACE"
        ],
        "tablet_buttons": [
          "KEY_LEFTCTRL+KEY_1",
          "KEY_LEFTCTRL+KEY_2",
          "KEY_B",
          "KEY_LEFTCTRL+KEY_LEFTALT",
          "KEY_LEFTCTRL+KEY_3",
          "KEY_SPACE"
        ]
      },
      "settings": {
        "swap_axis": False,
        "swap_direction_x": True,
        "swap_direction_y": False
      }
    }

    if self.injection_active:
      try:
        def convert_codes(target: List[str]) -> List[int]:
          temp = []
          for t in target: temp.extend([ecodes.ecodes[x] for x in t.split("+")])
          return temp

        def setEvents(target: List[int]) -> Dict[int, List[Any]]:
          if target == self.btn_codes: return {ecodes.EV_KEY: self.btn_codes}
          return {
            ecodes.EV_KEY: self.pen_codes,
            ecodes.EV_ABS: [
              (ecodes.ABS_X, AbsInfo(
                0, 0, self.settings["pen"]["max_x"], 0, 0, self.settings["pen"]["resolution_x"]
              )),
              (ecodes.ABS_Y, AbsInfo(
                0, 0, self.settings["pen"]["max_y"], 0, 0, self.settings["pen"]["resolution_y"]
              )),
              (ecodes.ABS_PRESSURE, AbsInfo(0, 0, self.settings["pen"]["max_pressure"], 0, 0, 0))
            ],
          }

        # Subtitle is indicated if the devices >= 2.
        def setUInput(any_events: Dict[int, List[Any]], subtitle: str) -> UInput:
          return UInput(events=any_events, name=self.settings["xinput_name"] + subtitle, version=0x3)

        def coordinate_axis(axis: str) -> int:
          return self.settings["pen"]["max_" + axis] if self.settings["settings"]["swap_direction_" + axis] else 0

        # Get the required ecodes from configuration.
        self.pen_codes = []
        self.btn_codes = []
        for k, v in self.settings["actions"].items():
          codes = self.btn_codes if k == "tablet_buttons" else self.pen_codes
          if isinstance(v, list): codes.extend(v)
          else: codes.append(v)

        self.pen_codes = convert_codes(self.pen_codes)
        self.btn_codes = convert_codes(self.btn_codes)

        # Find the device.
        # NOTE: Idk why, but it needs to be converted to int, although it didn't need to do so before.
        # Wait for the device.
        print("Scanning for tablet")

        while self.injection_active and not self.connection_active:
            self.dev = usb.core.find(
                idVendor=int(self.settings["vendor_id"], 16),
                idProduct=int(self.settings["product_id"], 16)
            )

            if self.dev is not None:
                self.connection_active = True
                break

            time.sleep(1)

        if not self.connection_active:
            return

        print("Tablet found")
        # Interface [0] refers to mass storage.
        # Interface [1] does not reac in any way.
        # Select end point for reading second interface [2] for actual data.
        # FIXME: I couldn't find a stylus in the interface [2] and
        # in the documentation it is present in interface [1], but it is not supported.
        self.ep = self.dev[0].interfaces()[2].endpoints()[0]
        # Reset the device (don't know why, but till it works don't touch it).
        self.dev.reset()

        # Drop default kernel driver from all devices.
        for i in [0, 1, 2]:
          if self.dev.is_kernel_driver_active(i):
            self.dev.detach_kernel_driver(i)

        # Set new configuration.
        self.dev.set_configuration()

        self.vpen = setUInput(setEvents(self.pen_codes), "")
        self.vbtn = setUInput(setEvents(self.btn_codes), "_buttons")

        # Direction and axis configuration.
        self.max_x = coordinate_axis("x")
        self.max_y = coordinate_axis("y")
        self.x1, self.x2, self.y1, self.y2 = (3, 2, 5, 4) if self.settings["settings"]["swap_axis"] else (5, 4, 3, 2)

        # TODO: migrate from classic Thread to qt QThread?
        # ^ Won't do ^
        self.injection_thread = Thread(target=self.read_device_data)
        self.injection_thread.daemon = True
        self.injection_thread.start()
        print("Injected")

      except Exception as e:
        self.connection_active = False
        print(f"Failed to start injection: {str(e)}")

  def read_device_data(self) -> None:
    while self.injection_active:
      try:
        data = self.dev.read(self.ep.bEndpointAddress, self.ep.wMaxPacketSize)
        # Pen codes.
        if data[1] in [192, 193]:
          pen_x = abs(self.max_x - (data[self.x1] * 255 + data[self.x2]))
          pen_y = abs(self.max_y - (data[self.y1] * 255 + data[self.y2]))
          pen_pressure = data[7] * 255 + data[6]
          self.vpen.write(ecodes.EV_ABS, ecodes.ABS_X, pen_x)
          self.vpen.write(ecodes.EV_ABS, ecodes.ABS_Y, pen_y)
          self.vpen.write(ecodes.EV_ABS, ecodes.ABS_PRESSURE, pen_pressure)
          if data[1] == 192: self.vpen.write(ecodes.EV_KEY, ecodes.BTN_TOUCH, 0)
          else: self.vpen.write(ecodes.EV_KEY, ecodes.BTN_TOUCH, 1)
        # Tablet button actions.
        elif data[0] == 2:
          press_type = 1
          if data[3] == 86: pressed = 0
          elif data[3] == 87: pressed = 1
          elif data[3] == 47: pressed = 2
          elif data[3] == 48: pressed = 3
          elif data[3] == 43: pressed = 4
          elif data[3] == 44: pressed = 5
          else: press_type = 0
          key_codes = self.settings["actions"]["tablet_buttons"][pressed].split("+")
          for key in key_codes:
            act = ecodes.ecodes[key]
            self.vbtn.write(ecodes.EV_KEY, act, press_type)
        # Flush.
        self.vpen.syn()
        self.vbtn.syn()
      except usb.core.USBError as e:
        if e.args[0] == 19:
          self.vpen.close()
          self.vbtn.close()
          self.connection_active = False
          print("Device disconnected")
          break

if __name__ == "__main__":
    while True:
        driver = Driver()

        while driver.connection_active:
            time.sleep(1)

        print("Restarting driver")
        time.sleep(1)
