using System;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using System.Management;

namespace XboxControllerBatteryLifeDisplay
{
    public partial class Form1 : Form
    {
        //// Constants for XInput
        //private const int ERROR_SUCCESS = 0;
        //private const int ERROR_DEVICE_NOT_CONNECTED = 1167;

        //private const byte BATTERY_DEVTYPE_GAMEPAD = 0x00;
        //private const byte BATTERY_TYPE_DISCONNECTED = 0x00;
        //private const byte BATTERY_TYPE_WIRED = 0x01;
        //private const byte BATTERY_TYPE_ALKALINE = 0x02;
        //private const byte BATTERY_TYPE_NIMH = 0x03;
        //private const byte BATTERY_TYPE_UNKNOWN = 0xFF;

        //private const byte BATTERY_LEVEL_EMPTY = 0x00;
        //private const byte BATTERY_LEVEL_LOW = 0x01;
        //private const byte BATTERY_LEVEL_MEDIUM = 0x02;
        //private const byte BATTERY_LEVEL_FULL = 0x03;

        // Structs for XInput
        //[StructLayout(LayoutKind.Sequential)]
        //public struct XInputGamepad
        //{
        //    public short wButtons;
        //    public byte bLeftTrigger;
        //    public byte bRightTrigger;
        //    public short sThumbLX;
        //    public short sThumbLY;
        //    public short sThumbRX;
        //    public short sThumbRY;
        //}

        //[StructLayout(LayoutKind.Sequential)]
        //public struct XInputState
        //{
        //    public int dwPacketNumber;
        //    public XInputGamepad Gamepad;
        //}

        //[StructLayout(LayoutKind.Sequential)]
        //public struct XInputBatteryInformation
        //{
        //    public byte BatteryType;
        //    public byte BatteryLevel;
        //}

        //// P/Invoke for XInput functions (using xinput1_4.dll for modern Windows)
        //[DllImport("xinput1_4.dll")]
        //public static extern int XInputGetState(int dwUserIndex, ref XInputState pState);

        //[DllImport("xinput1_4.dll")]
        //public static extern int XInputGetBatteryInformation(int dwUserIndex, byte devType, ref XInputBatteryInformation pBatteryInformation);
        public Form1()
        {
            InitializeComponent();
            BatteryTimer.Tick += BatteryTimer_Tick;  // Hook up the tick event
            BatteryTimer.Start();  // Start polling

            // Position to bottom-right with padding
            this.StartPosition = FormStartPosition.Manual;
            this.Location = new System.Drawing.Point(
                Screen.PrimaryScreen.WorkingArea.Width - this.Width - 10,
                Screen.PrimaryScreen.WorkingArea.Height - this.Height - 10
            );


        }

        private void BatteryTimer_Tick(object sender, EventArgs e)
        {
            string displayText = "Disconnected";
            System.Drawing.Color textColor = System.Drawing.Color.Red;

            try
            {
                // Broader query: find any matching Xbox controller device
                using (ManagementObjectSearcher searcher = new ManagementObjectSearcher(
                    @"root\CIMV2",
                    "SELECT * FROM Win32_PnPEntity WHERE Name LIKE '%Xbox Wireless Controller%'"))
                {
                    ManagementObjectCollection devices = searcher.Get();

                    bool isConnected = false;
                    ManagementObject activeDevice = null;

                    foreach (ManagementObject obj in devices)
                    {
                        string status = obj["Status"]?.ToString();  // "OK" = connected/working
                        if (status == "OK")
                        {
                            isConnected = true;
                            activeDevice = obj;
                            break;  // Use first active one
                        }
                    }

                    if (!isConnected || activeDevice == null)
                    {
                        batteryLabel1.Text = displayText;
                        batteryLabel1.ForeColor = textColor;
                        return;
                    }

                    // Device appears connected → try fresh battery fetch
                    ManagementBaseObject outParams = activeDevice.InvokeMethod("GetDeviceProperties", null, null);
                    ManagementBaseObject[] properties = (ManagementBaseObject[])outParams["deviceProperties"];

                    bool foundBattery = false;
                    foreach (ManagementBaseObject prop in properties)
                    {
                        string? keyName = prop["KeyName"]?.ToString();
                        if (keyName == "{104EA319-6EE2-4701-BD47-8DDBF425BBE5} 2")
                        {
                            object? data = prop["Data"];
                            if (data != null)
                            {
                                int batteryPercent = Convert.ToInt32(data);
                                displayText = $"Battery: {batteryPercent}%";

                                textColor = batteryPercent switch
                                {
                                    <= 10 => System.Drawing.Color.Red,
                                    <= 30 => System.Drawing.Color.Orange,
                                    <= 70 => System.Drawing.Color.Yellow,
                                    _ => System.Drawing.Color.Lime
                                };

                                foundBattery = true;
                            }
                            break;
                        }
                    }

                    if (!foundBattery)
                    {
                        displayText = "Connected (Battery Unknown)";
                        textColor = System.Drawing.Color.Orange;
                    }
                }
            }
            catch (Exception ex)
            {
                // On any error (e.g., stale device, invoke fail on disconnect) → disconnected
                displayText = "Disconnected";
                textColor = System.Drawing.Color.Red;
                // Optional debug: batteryLabel1.Text = $"Error: {ex.Message}";
            }

            batteryLabel1.Text = displayText;
            batteryLabel1.ForeColor = textColor;
        }

        private void label1_Click(object sender, EventArgs e)
        {

        }

        private void Form1_Load(object sender, EventArgs e)
        {

        }
    }
}
