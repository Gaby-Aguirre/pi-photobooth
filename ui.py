import os
import tkinter as tk
from PIL import Image, ImageTk, ImageFilter, ImageOps, ImageEnhance
from datetime import datetime
from picamera2 import Picamera2
from escpos.printer import File

# ---------------- SETTINGS ----------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BG_PATH = os.path.join(BASE_DIR, "photobooth_assets", "background.jpg")
PRINTER_DEVICE = "/dev/usb/lp0"

CAMERA_ROTATION = 90     # degrees counterclockwise. If the picture is upside down, use 270.
CONTRAST_CUTOFF = 2      # % of darkest/lightest pixels clipped when stretching contrast
CONTRAST_BOOST = 1.5     # 1.0 = no change, higher = punchier
BRIGHTNESS_BOOST = 1.05  # thermal printers print dark, so a small lift helps
BLUR_RADIUS = 0.4        # smoothing before dithering (was 0.8, lower keeps detail)

ACCENT = "#8e4e38"
BROWN = "#8e4e38"
# ------------------------------------------

root = tk.Tk()
root.attributes('-fullscreen', True)
root.config(cursor="none")

if os.path.exists(BG_PATH):
    bg_image = Image.open(BG_PATH).resize((800, 480))
else:
    bg_image = Image.new("RGB", (800, 480), "#2b1d16")  # fallback if the file is missing
bg_photo = ImageTk.PhotoImage(bg_image)

canvas = tk.Canvas(root, width=800, height=480, highlightthickness=0)
canvas.pack(fill="both", expand=True)

result_photo_ref = None
feed_photo_ref = None
running_feed = False

# Set up the camera once at startup
picam2 = Picamera2()
cam_config = picam2.create_still_configuration(main={"size": (1640, 1232), "format": "RGB888"})
picam2.configure(cam_config)
picam2.start()


def rotate_image(img):
    """Rotate a PIL image by CAMERA_ROTATION degrees, expanding the canvas."""
    if CAMERA_ROTATION % 360 == 0:
        return img
    return img.rotate(CAMERA_ROTATION, expand=True)


def fit_image(img, max_w, max_h):
    """Resize to fit inside max_w x max_h while keeping the aspect ratio."""
    scale = min(max_w / img.width, max_h / img.height)
    return img.resize((int(img.width * scale), int(img.height * scale)))


def outlined_text(x, y, text, font, fill, tags="ui", thickness=2):
    """Draw text with a white outline (tkinter has no built-in text stroke)."""
    for dx in range(-thickness, thickness + 1):
        for dy in range(-thickness, thickness + 1):
            if (dx or dy) and dx * dx + dy * dy <= thickness * thickness + 1:
                canvas.create_text(x + dx, y + dy, text=text, font=font, fill="white", tags=tags)
    canvas.create_text(x, y, text=text, font=font, fill=fill, tags=tags)


def draw_background():
    canvas.delete("all")
    canvas.create_image(0, 0, image=bg_photo, anchor="nw")


def draw_idle_screen():
    draw_background()
    outlined_text(400, 180, text="PHOTOBOOTH", font=("Times New Roman", 36, "bold"), fill=ACCENT, tags="ui")
    canvas.create_rectangle(300, 260, 500, 310, fill=ACCENT, outline="white", width=3, tags="ui")
    outlined_text(400, 285, text="TAP TO START", font=("Times New Roman", 16, "bold"), fill="white", tags="ui")
    canvas.bind("<Button-1>", lambda event: start_sequence())


def draw_ready_screen():
    draw_background()
    outlined_text(400, 240, text="GET READY!", font=("Times New Roman", 40, "bold"), fill=ACCENT, tags="ui")


def start_sequence():
    canvas.unbind("<Button-1>")
    draw_ready_screen()
    root.after(2000, begin_live_feed_countdown)


def begin_live_feed_countdown():
    global running_feed
    draw_background()
    running_feed = True
    update_live_feed()
    run_countdown(3)


def update_live_feed():
    global feed_photo_ref
    if not running_feed:
        return
    frame = picam2.capture_array()

    img = Image.fromarray(frame[:, :, ::-1])  # swap BGR -> RGB
    img = rotate_image(img)
    img = fit_image(img, 520, 400)
    feed_photo_ref = ImageTk.PhotoImage(img)
    canvas.delete("feed")
    canvas.create_image(400, 220, image=feed_photo_ref, tags="feed")
    canvas.tag_raise("countdown_num")
    root.after(150, update_live_feed)


def run_countdown(number):
    if number > 0:
        canvas.delete("countdown_num")
        outlined_text(400, 220, text=str(number), font=("Times New Roman", 130, "bold"),
                           fill=ACCENT, tags="countdown_num", thickness=5)
        canvas.tag_raise("countdown_num")
        root.after(1000, lambda: run_countdown(number - 1))
    else:
        flash_and_capture()


def flash_and_capture():
    global running_feed
    running_feed = False
    canvas.delete("all")
    canvas.create_rectangle(0, 0, 800, 480, fill="white", outline="white")
    canvas.update()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_filename = f"photo_{timestamp}.jpg"

    # Capture EXACTLY at the flash, rotate it, then save
    photo = picam2.capture_image("main").convert("RGB")
    photo = rotate_image(photo)
    photo.save(raw_filename, quality=95)

    root.after(100, lambda: after_capture(raw_filename))


def draw_loading_screen():
    draw_background()
    outlined_text(400, 240, text="LOADING….", font=("Times New Roman", 28, "bold"), fill=ACCENT, tags="ui")


def after_capture(raw_filename):
    global result_photo_ref
    draw_loading_screen()
    canvas.update()

    dithered_filename = raw_filename.replace(".jpg", "_dithered.png")
    dither_photo(raw_filename, dithered_filename)

    # Show the ORIGINAL color photo, not the dithered one
    draw_background()
    orig_img = Image.open(raw_filename)
    orig_resized = fit_image(orig_img, 620, 380)
    result_photo_ref = ImageTk.PhotoImage(orig_resized)
    canvas.create_image(400, 220, image=result_photo_ref, tags="ui")
    outlined_text(400, 440, text="HERES YOUR PIC", font=("Times New Roman", 16, "bold"), fill=ACCENT, tags="ui")

    root.after(2000, lambda: start_printing(dithered_filename))


def draw_printing_screen():
    draw_background()
    # Printer body
    canvas.create_rectangle(340, 170, 460, 230, fill="white", outline=BROWN, width=3, tags="ui")
    # Paper slot on top
    canvas.create_rectangle(355, 160, 445, 172, fill="#b56441", outline=BROWN, width=2, tags="ui")
    # Paper coming out, printed on
    canvas.create_rectangle(365, 230, 435, 280, fill="white", outline=BROWN, width=2, tags="ui")
    canvas.create_line(375, 240, 425, 240, fill="#874d37", width=1, tags="ui")
    canvas.create_line(375, 250, 425, 250, fill="#874d37", width=1, tags="ui")
    canvas.create_line(375, 260, 405, 260, fill="#874d37", width=1, tags="ui")
    # Small light on the printer body
    canvas.create_oval(395, 195, 405, 205, fill="#ba6849", outline="#874d37", tags="ui")

    outlined_text(400, 320, text="PRINTING YOUR PICTURE", font=("Times New Roman", 16, "bold"), fill=ACCENT, tags="ui")
    outlined_text(400, 350, text="give it a minute", font=("Times New Roman", 13, "bold"), fill=ACCENT, tags="ui")


def start_printing(dithered_filename):
    draw_printing_screen()
    canvas.update()
    print_receipt(dithered_filename)
    root.after(5000, draw_idle_screen)


def dither_photo(input_filename, output_filename):
    img = Image.open(input_filename)
    target_width = 384
    aspect_ratio = img.height / img.width
    target_height = int(target_width * aspect_ratio)
    img_resized = img.resize((target_width, target_height), Image.LANCZOS)

    img_gray = img_resized.convert('L')

    # More contrast: stretch the tones, boost contrast, lift brightness slightly
    img_gray = ImageOps.autocontrast(img_gray, cutoff=CONTRAST_CUTOFF)
    img_gray = ImageEnhance.Contrast(img_gray).enhance(CONTRAST_BOOST)
    img_gray = ImageEnhance.Brightness(img_gray).enhance(BRIGHTNESS_BOOST)

    img_smoothed = img_gray.filter(ImageFilter.GaussianBlur(radius=BLUR_RADIUS))
    img_smoothed = img_smoothed.filter(ImageFilter.UnsharpMask(radius=1.5, percent=120, threshold=2))

    img_dithered = img_smoothed.convert('1')
    img_dithered.save(output_filename)


def print_receipt(dithered_filename):
    try:
        printer = File(PRINTER_DEVICE)
        img = Image.open(dithered_filename)
        printer.image(img)
        printer.ln(3)  # feed a little paper so the photo isn't cut off
        printer.cut()
        printer.close()
        print("Print job sent successfully!")
    except Exception as e:
        print(f"Print failed: {e}")


draw_idle_screen()
root.mainloop()
