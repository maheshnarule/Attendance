import qrcode
from PIL import Image, ImageDraw
import os
from datetime import datetime

class QRManager:
    def __init__(self):
        self.qr_dir = "qr_codes"
        os.makedirs(self.qr_dir, exist_ok=True)
    
    def generate_qr(self, qr_token, lecture_id, expiry_minutes=2):
        """Generate QR code image with expiry info"""
        
        # Create QR data URL
        qr_data = f"https://your-domain.com/attendance?qr={qr_token}"
        
        # Generate QR code
        qr = qrcode.QRCode(
            version=5,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_data)
        qr.make(fit=True)
        
        # Create QR image
        qr_image = qr.make_image(fill_color="black", back_color="white").convert('RGB')
        
        # Add text overlay
        draw = ImageDraw.Draw(qr_image)
        
        # Save QR image using the token filename so it can be served by the app
        filename = f"{qr_token}.png"
        filepath = os.path.join(self.qr_dir, filename)
        qr_image.save(filepath)
        
        return filepath, f"/qr-image/{qr_token}"
    
    def display_qr_on_screen(self, qr_path):
        """Display QR code in GUI window"""
        from PIL import ImageTk
        import tkinter as tk
        
        root = tk.Tk()
        root.title("QR Code - Scan for Attendance")
        
        img = Image.open(qr_path)
        # Resize for better visibility
        img = img.resize((400, 400), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        
        label = tk.Label(root, image=photo)
        label.pack(pady=20)
        
        # Show expiry timer
        timer_label = tk.Label(root, text="Valid for 2:00", font=("Arial", 14))
        timer_label.pack()
        
        # Countdown timer
        def update_timer(seconds_left):
            if seconds_left <= 0:
                timer_label.config(text="EXPIRED!", fg="red")
                root.after(3000, root.destroy)
            else:
                mins = seconds_left // 60
                secs = seconds_left % 60
                timer_label.config(text=f"Valid for {mins}:{secs:02d}")
                root.after(1000, update_timer, seconds_left - 1)
        
        root.after(100, update_timer, 120)  # 2 minutes
        root.mainloop()