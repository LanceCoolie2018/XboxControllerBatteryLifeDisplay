namespace XboxControllerBatteryLifeDisplay
{
    partial class Form1
    {
        /// <summary>
        ///  Required designer variable.
        /// </summary>
        private System.ComponentModel.IContainer components = null;

        /// <summary>
        ///  Clean up any resources being used.
        /// </summary>
        /// <param name="disposing">true if managed resources should be disposed; otherwise, false.</param>
        protected override void Dispose(bool disposing)
        {
            if (disposing && (components != null))
            {
                components.Dispose();
            }
            base.Dispose(disposing);
        }

        #region Windows Form Designer generated code

        /// <summary>
        ///  Required method for Designer support - do not modify
        ///  the contents of this method with the code editor.
        /// </summary>
        private void InitializeComponent()
        {
            components = new System.ComponentModel.Container();
            batteryLabel1 = new Label();
            BatteryTimer = new System.Windows.Forms.Timer(components);
            SuspendLayout();
            // 
            // batteryLabel1
            // 
            batteryLabel1.AutoSize = true;
            batteryLabel1.BackColor = Color.Transparent;
            batteryLabel1.Font = new Font("Segoe UI", 20.25F, FontStyle.Regular, GraphicsUnit.Point, 0);
            batteryLabel1.ForeColor = Color.Black;
            batteryLabel1.Location = new Point(12, 9);
            batteryLabel1.Name = "batteryLabel1";
            batteryLabel1.Size = new Size(144, 37);
            batteryLabel1.TabIndex = 0;
            batteryLabel1.Text = "Checking...";
            batteryLabel1.Click += label1_Click;
            // 
            // BatteryTimer
            // 
            BatteryTimer.Enabled = true;
            BatteryTimer.Interval = 1000;
            // 
            // Form1
            // 
            AutoScaleDimensions = new SizeF(7F, 15F);
            AutoScaleMode = AutoScaleMode.Font;
            BackColor = Color.FromArgb(224, 224, 224);
            ClientSize = new Size(546, 61);
            Controls.Add(batteryLabel1);
            FormBorderStyle = FormBorderStyle.None;
            Name = "Form1";
            Text = "Form1";
            TopMost = true;
            TransparencyKey = Color.FromArgb(224, 224, 224);
            Load += Form1_Load;
            ResumeLayout(false);
            PerformLayout();
        }

        #endregion

        private Label batteryLabel1;
        private System.Windows.Forms.Timer BatteryTimer;
    }
}
