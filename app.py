import os
import glob
import shutil
import json
import time
from datetime import datetime
from io import BytesIO
import mimetypes
from flask import Flask, request, jsonify, send_file, Response
from PIL import Image, ImageOps
import pillow_heif
import piexif

# Register HEIF opener
pillow_heif.register_heif_opener()

app = Flask(__name__)

# --- Configuration ---
THUMBNAIL_SIZE = (600, 600)
GIF_SIZE = (600, 800)
TRASH_DIR_NAME = "_TRASH"
KEEP_DIR_NAME = "_KEPT"

class ImageManager:
    def __init__(self):
        self.current_folder = ""
        self.groups = [] 
    
    def get_photo_datetime(self, file):
        """Read photo date. Safe for videos (uses file stats)."""
        try:
            # Skip Pillow for videos to prevent crash
            if file.lower().endswith(('.mov', '.mp4', '.avi', '.mkv')):
                return datetime.fromtimestamp(os.path.getmtime(file))

            if file.lower().endswith(".heic"):
                heif_file = pillow_heif.read_heif(file)
                exif_bytes = heif_file.info.get("exif", None)
                if exif_bytes:
                    exif_dict = piexif.load(exif_bytes)
                    if "Exif" in exif_dict and piexif.ExifIFD.DateTimeOriginal in exif_dict["Exif"]:
                        value = exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal].decode()
                        return datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
            else:
                img = Image.open(file)
                exif = img.info.get("exif")
                if exif:
                    exif_dict = piexif.load(exif)
                    if "Exif" in exif_dict and piexif.ExifIFD.DateTimeOriginal in exif_dict["Exif"]:
                        value = exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal].decode()
                        return datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
        except Exception as e:
            print(f"Read Date Error {file}: {e}")

        # fallback: File creation/modification time
        return datetime.fromtimestamp(os.path.getmtime(file))

    def scan_folder(self, folder_path, time_threshold=2.0):
        self.current_folder = folder_path
        # Added *.MP4 specifically for case-sensitive filesystems or specific camera outputs
        extensions = ("*.jpg", "*.jpeg", "*.png", "*.heic", "*.HEIC", "*.JPG", "*.PNG", "*.mov", "*.MOV", "*.mp4", "*.MP4", "*.gif")
        files = []
        for ext in extensions:
            files.extend(glob.glob(os.path.join(folder_path, ext)))
        
        # Filter special folders
        files = [f for f in files if TRASH_DIR_NAME not in f and KEEP_DIR_NAME not in f]

        print(f"Sorting {len(files)} files...")
        
        files_with_dates = []
        for f in files:
            files_with_dates.append((f, self.get_photo_datetime(f)))
        
        files_with_dates.sort(key=lambda x: x[1])

        self.groups = []
        if not files_with_dates:
            return 0

        current_group = [files_with_dates[0]]
        
        for i in range(1, len(files_with_dates)):
            curr_file, curr_date = files_with_dates[i]
            prev_file, prev_date = files_with_dates[i-1]
            
            delta = (curr_date - prev_date).total_seconds()
            
            # Grouping Logic
            is_gif = curr_file.lower().endswith('.gif')
            prev_is_gif = prev_file.lower().endswith('.gif')

            if delta <= time_threshold and not is_gif and not prev_is_gif:
                current_group.append((curr_file, curr_date))
            else:
                self.groups.append(current_group)
                current_group = [(curr_file, curr_date)]
        
        if current_group:
            self.groups.append(current_group)
            
        print(f"Created {len(self.groups)} groups.")
        return len(self.groups)

manager = ImageManager()

def get_safe_filename_date(folder, date_obj, original_ext):
    date_str = date_obj.strftime("%Y%m%d")
    base_name = date_str + original_ext
    
    if not os.path.exists(os.path.join(folder, base_name)):
        return base_name
    
    counter = 1
    while True:
        new_name = f"{date_str}_{counter}{original_ext}"
        if not os.path.exists(os.path.join(folder, new_name)):
            return new_name
        counter += 1

@app.route('/')
def index():
    return send_file('index.html')

@app.route('/api/browse', methods=['POST'])
def browse_folder():
    """
    Simulates 'ls' and helps with directory navigation.
    """
    data = request.json
    path = data.get('path')
    
    # Default to user home directory if no path provided
    if not path:
        path = os.path.expanduser("~")
    
    if not os.path.exists(path):
        return jsonify({"error": "Path not found"}), 404
        
    if not os.path.isdir(path):
        return jsonify({"error": "Not a directory"}), 400
        
    try:
        # Get directory contents
        items = os.listdir(path)
        items.sort()
        
        # Separate folders and compatible files
        folders = [i for i in items if os.path.isdir(os.path.join(path, i)) and not i.startswith('.')]
        
        extensions = ('.jpg', '.jpeg', '.png', '.heic', '.mov', '.mp4', '.gif')
        files = [i for i in items if os.path.isfile(os.path.join(path, i)) and not i.startswith('.') and i.lower().endswith(extensions)]
        
        abs_path = os.path.abspath(path)
        parent = os.path.dirname(abs_path)
        
        return jsonify({
            "current_path": abs_path,
            "folders": folders,
            "files": files,
            "parent": parent if parent != abs_path else None,
            "sep": os.sep
        })
    except Exception as e:
        return jsonify({"error": f"Access denied or error: {str(e)}"}), 500

@app.route('/api/scan', methods=['POST'])
def scan():
    data = request.json
    folder = data.get('path')
    if not os.path.exists(folder):
        return jsonify({"error": "Folder not found"}), 404
    
    count = manager.scan_folder(folder)
    
    response_data = []
    for idx, group in enumerate(manager.groups):
        f_path = group[0][0].lower()
        g_type = "image"
        if f_path.endswith(('.mov', '.mp4')): g_type = "video"
        elif f_path.endswith('.gif'): g_type = "gif"

        response_data.append({
            "id": idx,
            "count": len(group),
            "timestamp": group[0][1].strftime("%Y-%m-%d %H:%M:%S"),
            "files": [os.path.basename(f[0]) for f in group],
            "type": g_type
        })
        
    return jsonify({"groups": response_data, "base_path": manager.current_folder})

@app.route('/api/media')
def get_media():
    try:
        group_id = int(request.args.get('groupId'))
        img_idx = int(request.args.get('imgIndex', 0))
        is_thumb = request.args.get('thumb', 'true') == 'true'
        
        if group_id >= len(manager.groups):
            return "Invalid group", 404
            
        file_path = manager.groups[group_id][img_idx][0]
        filename = os.path.basename(file_path)
        ext = filename.lower()
        
        # Stream Video/GIF directly
        if ext.endswith(('.mov', '.mp4', '.gif')):
            mime = 'video/mp4' if ext.endswith('.mp4') else 'video/quicktime'
            if ext.endswith('.gif'): mime = 'image/gif'
            return send_file(file_path, mimetype=mime)

        # Handle Image
        img = Image.open(file_path)
        
        if not is_thumb:
             img_io = BytesIO()
             img = img.convert('RGB')
             img.save(img_io, 'JPEG', quality=90)
             img_io.seek(0)
             return send_file(img_io, mimetype='image/jpeg')

        img.thumbnail(THUMBNAIL_SIZE)
        img = ImageOps.exif_transpose(img)
        
        img_io = BytesIO()
        img.convert('RGB').save(img_io, 'JPEG', quality=70)
        img_io.seek(0)
        return send_file(img_io, mimetype='image/jpeg')
    except Exception as e:
        print(f"Error serving media: {e}")
        return str(e), 500

@app.route('/api/generate_preview_gif', methods=['POST'])
def generate_preview_gif():
    data = request.json
    group_id = data.get('groupId')
    mode = data.get('mode', 'normal')
    duration = data.get('duration', 200)
    included_indices = data.get('includedIndices') # List of integers to include
    
    group = manager.groups[group_id]
    
    # Filter files based on inclusion list
    target_files = []
    if included_indices is not None:
        # Sort indices to maintain order, filter bounds
        sorted_indices = sorted([i for i in included_indices if 0 <= i < len(group)])
        target_files = [group[i] for i in sorted_indices]
    else:
        target_files = group

    frames = []
    
    try:
        for file_info in target_files:
            f_path = file_info[0]
            if f_path.lower().endswith(('.mov', '.mp4')): continue 

            img = Image.open(f_path)
            if img.width > 600:
                ratio = 600 / float(img.width)
                new_height = int(img.height * ratio)
                img = img.resize((600, new_height), Image.LANCZOS)
            
            img = ImageOps.exif_transpose(img)
            img = img.convert("P", palette=Image.ADAPTIVE, colors=64)
            frames.append(img)

        if not frames: return "No valid frames selected", 400

        output_frames = frames
        if mode == 'bounce':
            output_frames = frames + frames[-2:0:-1]

        img_io = BytesIO()
        output_frames[0].save(
            img_io,
            format='GIF',
            save_all=True,
            append_images=output_frames[1:],
            duration=duration,
            loop=0,
            optimize=True
        )
        img_io.seek(0)
        return send_file(img_io, mimetype='image/gif')

    except Exception as e:
        return str(e), 500

@app.route('/api/action', methods=['POST'])
def take_action():
    data = request.json
    action = data.get('action') 
    group_id = data.get('groupId')
    group = manager.groups[group_id]
    base_folder = manager.current_folder
    
    trash_path = os.path.join(base_folder, TRASH_DIR_NAME)
    kept_path = os.path.join(base_folder, KEEP_DIR_NAME)
    
    for p in [trash_path, kept_path]:
        os.makedirs(p, exist_ok=True)

    try:
        if action == 'trash_all':
            for f_info in group:
                src = f_info[0]
                dst = os.path.join(trash_path, os.path.basename(src))
                if os.path.exists(dst):
                     base, ext = os.path.splitext(os.path.basename(src))
                     dst = os.path.join(trash_path, f"{base}_{int(time.time())}{ext}")
                shutil.move(src, dst)
        
        elif action == 'keep_all':
            rotation = data.get('rotation', 0)
            crop = data.get('crop', None) 

            for f_info in group:
                src = f_info[0]
                date_obj = f_info[1]
                _, ext = os.path.splitext(src)
                
                new_filename = get_safe_filename_date(kept_path, date_obj, ext)
                dst = os.path.join(kept_path, new_filename)
                
                is_video = src.lower().endswith(('.mov', '.mp4', '.avi', '.mkv'))
                
                if not is_video and (rotation != 0 or crop is not None):
                    try:
                        img = Image.open(src)
                        
                        # Apply Rotation
                        if rotation != 0:
                            img = img.rotate(-rotation, expand=True)
                            
                        # Apply Crop
                        if crop:
                            w, h = img.size
                            left = crop['x'] * w
                            top = crop['y'] * h
                            right = (crop['x'] + crop['w']) * w
                            bottom = (crop['y'] + crop['h']) * h
                            img = img.crop((left, top, right, bottom))
                            
                        # Save
                        exif = img.info.get('exif')
                        if exif:
                             img.save(dst, quality=95, exif=exif)
                        else:
                             img.save(dst, quality=95)
                             
                        os.remove(src) 
                    except Exception as e:
                        print(f"Processing error, falling back to move: {e}")
                        shutil.move(src, dst)
                else:
                    shutil.move(src, dst)

        elif action == 'save_gif':
            mode = data.get('gifMode', 'normal')
            duration = data.get('duration', 100)
            place = data.get('place', '').strip()
            included_indices = data.get('includedIndices')
            
            place_safe = place.replace(" ", "_") if place else "Unknown"

            # Filter group for GIF generation only
            target_group = group
            if included_indices is not None:
                sorted_indices = sorted([i for i in included_indices if 0 <= i < len(group)])
                target_group = [group[i] for i in sorted_indices]

            frames = []
            for file_info in target_group:
                if file_info[0].lower().endswith(('.mov', '.mp4')): continue
                img = Image.open(file_info[0])
                if img.width > 1200:
                    ratio = 1200 / float(img.width)
                    new_height = int(img.height * ratio)
                    img = img.resize((1200, new_height), Image.LANCZOS)
                img = ImageOps.exif_transpose(img)
                img = img.convert("P", palette=Image.ADAPTIVE, colors=256)
                frames.append(img)
            
            if not frames: return jsonify({"error": "No images selected"}), 400

            output_frames = frames
            if mode == 'bounce':
                output_frames = frames + frames[-2:0:-1]
            
            date_str = group[0][1].strftime("%Y%m%d")
            base_filename = f"{date_str}_{place_safe}"
            
            gif_filename = f"{base_filename}.gif"
            counter = 1
            while os.path.exists(os.path.join(kept_path, gif_filename)):
                gif_filename = f"{base_filename}_{counter}.gif"
                counter += 1

            save_path = os.path.join(kept_path, gif_filename)
            output_frames[0].save(save_path, save_all=True, append_images=output_frames[1:], duration=duration, loop=0, optimize=True)
            
            return jsonify({"success": True})

        elif action == 'batch_organize':
            trash_indices = data.get('trashIndices', [])
            for idx in trash_indices:
                if idx < len(group):
                    src = group[idx][0]
                    dst = os.path.join(trash_path, os.path.basename(src))
                    if os.path.exists(dst):
                         base, ext = os.path.splitext(os.path.basename(src))
                         dst = os.path.join(trash_path, f"{base}_{int(time.time())}{ext}")
                    if os.path.exists(src): shutil.move(src, dst)
            
            for f_info in group:
                src = f_info[0]
                date_obj = f_info[1]
                if os.path.exists(src):
                    _, ext = os.path.splitext(src)
                    new_filename = get_safe_filename_date(kept_path, date_obj, ext)
                    dst = os.path.join(kept_path, new_filename)
                    shutil.move(src, dst)

        return jsonify({"success": True})

    except Exception as e:
        print(e)
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    print("Starting server at http://localhost:3000")
    app.run(host='0.0.0.0', port=3000, debug=True)