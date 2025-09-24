#!/usr/bin/env python3
"""
Advanced Video File Converter
Searches for .mp4 and .mkv files in a directory tree and converts them to optimized MP4 format.
Features: Simple, reliable progress tracking with minimal output interference.
"""

import os
import sys
import subprocess
import argparse
import logging
import time
import threading
from pathlib import Path
from typing import List, Tuple, Optional
import shutil
from datetime import datetime, timedelta
import re

# Configure logging
def setup_logging(verbose: bool = False):
    """Setup logging configuration."""
    log_format = '%(asctime)s - %(levelname)s - %(message)s'
    log_level = logging.DEBUG if verbose else logging.INFO
    
    # Create logs directory if it doesn't exist
    log_dir = Path('logs')
    log_dir.mkdir(exist_ok=True)
    
    # Only log to file to avoid interfering with progress display
    file_handler = logging.FileHandler(
        log_dir / f'video_converter_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(logging.Formatter(log_format))
    
    logger = logging.getLogger(__name__)
    logger.setLevel(log_level)
    logger.addHandler(file_handler)
    
    # Add console handler only for verbose mode
    if verbose:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.ERROR)
        console_handler.setFormatter(logging.Formatter('ERROR: %(message)s'))
        logger.addHandler(console_handler)
    
    return logger

class SimpleProgressTracker:
    """Simple, reliable progress tracker."""
    
    def __init__(self, total_files: int):
        self.total_files = total_files
        self.current_index = 0
        self.completed_files = 0
        self.failed_files = 0
        self.skipped_files = 0
        self.start_time = time.time()
        self.file_times = []
        
    def start_file(self, index: int):
        """Mark the start of a file conversion."""
        self.current_index = index
        self.current_file_start = time.time()
        
    def complete_file(self, success: bool, skipped: bool = False):
        """Mark the completion of a file conversion."""
        if hasattr(self, 'current_file_start'):
            duration = time.time() - self.current_file_start
            self.file_times.append(duration)
            # Keep only last 10 times for ETA calculation
            if len(self.file_times) > 10:
                self.file_times.pop(0)
            
        if skipped:
            self.skipped_files += 1
        elif success:
            self.completed_files += 1
        else:
            self.failed_files += 1
    
    def get_eta_minutes(self) -> Optional[int]:
        """Get estimated time remaining in minutes."""
        if not self.file_times:
            return None
            
        processed = self.completed_files + self.failed_files + self.skipped_files
        remaining = self.total_files - processed
        
        if remaining <= 0:
            return 0
            
        avg_time = sum(self.file_times) / len(self.file_times)
        eta_seconds = remaining * avg_time
        return int(eta_seconds / 60)
    
    def get_elapsed_minutes(self) -> int:
        """Get elapsed time in minutes."""
        return int((time.time() - self.start_time) / 60)

class FFmpegProgressParser:
    """Simple FFmpeg progress parser."""
    
    def __init__(self):
        self.duration_seconds = None
        self.current_seconds = None
        
    def parse_duration(self, line: str):
        """Parse duration from FFmpeg output."""
        if 'Duration:' in line:
            match = re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)', line)
            if match:
                h, m, s = match.groups()
                self.duration_seconds = int(h) * 3600 + int(m) * 60 + float(s)
    
    def parse_progress(self, line: str):
        """Parse current time from FFmpeg output."""
        if 'time=' in line:
            match = re.search(r'time=(\d+):(\d+):(\d+\.\d+)', line)
            if match:
                h, m, s = match.groups()
                self.current_seconds = int(h) * 3600 + int(m) * 60 + float(s)
    
    def get_progress_percent(self) -> Optional[int]:
        """Get progress as integer percentage."""
        if self.duration_seconds and self.current_seconds and self.duration_seconds > 0:
            percent = min(100, int((self.current_seconds / self.duration_seconds) * 100))
            return percent
        return None

class VideoConverter:
    def __init__(self, source_dir: str, output_dir: str = None, skip_existing: bool = True):
        """Initialize the video converter."""
        self.source_dir = Path(source_dir).resolve()
        self.output_dir = Path(output_dir).resolve() if output_dir else self.source_dir / "converted"
        self.skip_existing = skip_existing
        self.logger = logging.getLogger(__name__)
        
        # Supported input formats
        self.supported_formats = {'.mp4', '.mkv'}
        
        # FFmpeg settings optimized for quality and size
        self.ffmpeg_args = [
            '-c:v', 'libx264',           # Video codec
            '-preset', 'medium',         # Balanced preset
            '-crf', '23',                # Quality (lower = better, 18-28 range)
            '-c:a', 'aac',               # Audio codec
            '-b:a', '128k',              # Audio bitrate
            '-movflags', '+faststart',   # Optimize for streaming
            '-pix_fmt', 'yuv420p',       # Pixel format for compatibility
            '-threads', '0',             # Use all available CPU threads
        ]
        
    def check_dependencies(self) -> bool:
        """Check if FFmpeg is installed and available."""
        try:
            result = subprocess.run(['ffmpeg', '-version'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                version_line = result.stdout.split('\n')[0]
                self.logger.info(f"FFmpeg found: {version_line}")
                print("✓ FFmpeg found and ready")
                return True
            else:
                print("✗ FFmpeg not working properly")
                return False
        except (subprocess.TimeoutExpired, FileNotFoundError):
            print("✗ FFmpeg not found. Please install FFmpeg: https://ffmpeg.org/download.html")
            return False
        except Exception as e:
            print(f"✗ Error checking FFmpeg: {e}")
            return False
    
    def find_video_files(self) -> List[Path]:
        """Recursively find all supported video files."""
        print("Scanning for video files...")
        video_files = []
        
        try:
            for root, dirs, files in os.walk(self.source_dir):
                for file in files:
                    file_path = Path(root) / file
                    if file_path.suffix.lower() in self.supported_formats:
                        video_files.append(file_path)
                        
        except Exception as e:
            self.logger.error(f"Error searching for video files: {e}")
            print(f"Error scanning files: {e}")
            
        print(f"✓ Found {len(video_files)} video files")
        return sorted(video_files)
    
    def get_output_path(self, input_path: Path) -> Path:
        """Generate output path for converted file."""
        rel_path = input_path.relative_to(self.source_dir)
        
        # Generate unique filename if converting .mp4 to .mp4
        if input_path.suffix.lower() == '.mp4':
            output_name = f"{rel_path.stem}_optimized.mp4"
        else:
            output_name = f"{rel_path.stem}.mp4"
            
        output_path = self.output_dir / rel_path.parent / output_name
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        return output_path
    
    def format_file_size(self, size_bytes: int) -> str:
        """Format file size in human readable format."""
        if size_bytes == 0:
            return "0B"
        
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f}{unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f}TB"
    
    def get_file_size(self, file_path: Path) -> int:
        """Get file size in bytes."""
        try:
            return file_path.stat().st_size
        except:
            return 0
    
    def print_progress_header(self):
        """Print the progress table header."""
        print("\n" + "="*100)
        print(f"{'File':<40} {'Directory':<30} {'Progress':<15} {'Status':<10}")
        print("="*100)
    
    def print_file_progress(self, filename: str, directory: str, progress: str, status: str):
        """Print progress for current file."""
        # Truncate strings to fit columns
        filename = filename[:37] + "..." if len(filename) > 40 else filename
        directory = directory[:27] + "..." if len(directory) > 30 else directory
        
        # Clear line and print new progress
        sys.stdout.write(f"\r{filename:<40} {directory:<30} {progress:<15} {status:<10}")
        sys.stdout.flush()
    
    def print_file_result(self, filename: str, directory: str, result: str, size_info: str = ""):
        """Print final result for a file."""
        filename = filename[:37] + "..." if len(filename) > 40 else filename
        directory = directory[:27] + "..." if len(directory) > 30 else directory
        
        # Move to new line and print result
        sys.stdout.write(f"\n{filename:<40} {directory:<30} {result:<15} {size_info}")
        sys.stdout.flush()
    
    def convert_video(self, input_path: Path, output_path: Path, file_index: int, total_files: int, tracker: SimpleProgressTracker) -> Tuple[bool, str]:
        """Convert a single video file."""
        try:
            # Get display info
            filename = input_path.name
            directory = str(input_path.parent.relative_to(self.source_dir))
            if directory == ".":
                directory = "root"
            
            # Skip if output file already exists
            if self.skip_existing and output_path.exists():
                self.print_file_result(filename, directory, "SKIPPED", "(already exists)")
                return True, "skipped"
            
            # Get input file size
            input_size = self.get_file_size(input_path)
            input_size_str = self.format_file_size(input_size)
            
            # Build FFmpeg command
            cmd = [
                'ffmpeg', '-i', str(input_path),
                *self.ffmpeg_args,
                '-progress', 'pipe:2',
                '-nostats', '-loglevel', 'error',
                '-y', str(output_path)
            ]
            
            self.logger.debug(f"Converting: {filename}")
            
            # Start conversion process
            parser = FFmpegProgressParser()
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                universal_newlines=True
            )
            
            last_update = 0
            last_percent = 0
            
            # Monitor progress
            while True:
                line = process.stderr.readline()
                if line == '' and process.poll() is not None:
                    break
                
                if line:
                    parser.parse_duration(line.strip())
                    parser.parse_progress(line.strip())
                    
                    # Update display every 2 seconds
                    current_time = time.time()
                    if current_time - last_update >= 2.0:
                        percent = parser.get_progress_percent()
                        if percent is not None and percent != last_percent:
                            progress_str = f"{percent}%"
                            eta = tracker.get_eta_minutes()
                            eta_str = f"ETA: {eta}m" if eta else ""
                            status = f"{file_index}/{total_files} {eta_str}"
                            
                            self.print_file_progress(filename, directory, progress_str, status)
                            last_percent = percent
                            last_update = current_time
            
            # Wait for completion
            process.wait()
            
            if process.returncode == 0:
                # Success
                output_size = self.get_file_size(output_path)
                output_size_str = self.format_file_size(output_size)
                
                # Calculate savings
                if input_size > 0:
                    savings = ((input_size - output_size) / input_size) * 100
                    size_info = f"{input_size_str} -> {output_size_str} ({savings:+.1f}%)"
                else:
                    size_info = f"-> {output_size_str}"
                
                self.print_file_result(filename, directory, "SUCCESS", size_info)
                return True, "success"
            else:
                # Failed
                if output_path.exists():
                    try:
                        output_path.unlink()
                    except:
                        pass
                
                self.print_file_result(filename, directory, "FAILED", "conversion error")
                return False, "failed"
                
        except Exception as e:
            self.logger.error(f"Error converting {input_path}: {e}")
            self.print_file_result(filename, directory, "ERROR", str(e)[:30])
            return False, "error"
    
    def convert_all(self) -> dict:
        """Convert all found video files."""
        print("Advanced Video File Converter")
        print(f"Source: {self.source_dir}")
        print(f"Output: {self.output_dir}")
        
        if not self.check_dependencies():
            return {'error': 'FFmpeg not available'}
        
        if not self.source_dir.exists():
            print(f"Error: Source directory does not exist")
            return {'error': 'Source directory not found'}
        
        # Find all video files
        video_files = self.find_video_files()
        
        if not video_files:
            print("No video files found to convert")
            return {'total': 0, 'success': 0, 'failed': 0, 'skipped': 0}
        
        # Initialize progress tracking
        tracker = SimpleProgressTracker(len(video_files))
        
        # Statistics
        stats = {'total': len(video_files), 'success': 0, 'failed': 0, 'skipped': 0}
        failed_files = []
        
        # Print progress header
        self.print_progress_header()
        
        # Process each file
        for i, input_path in enumerate(video_files, 1):
            try:
                output_path = self.get_output_path(input_path)
                tracker.start_file(i)
                
                success, result_type = self.convert_video(input_path, output_path, i, len(video_files), tracker)
                tracker.complete_file(success, result_type == "skipped")
                
                # Update statistics
                if result_type == "skipped":
                    stats['skipped'] += 1
                elif success:
                    stats['success'] += 1
                else:
                    stats['failed'] += 1
                    failed_files.append(str(input_path))
                    
            except KeyboardInterrupt:
                print(f"\n\nConversion interrupted by user!")
                print(f"Processed: {i-1}/{len(video_files)} files")
                break
            except Exception as e:
                self.logger.error(f"Unexpected error processing {input_path}: {e}")
                stats['failed'] += 1
                failed_files.append(str(input_path))
                tracker.complete_file(False, False)
        
        # Final summary
        print("\n" + "="*100)
        elapsed_mins = tracker.get_elapsed_minutes()
        print(f"CONVERSION COMPLETE! Total time: {elapsed_mins} minutes")
        print(f"Results: {stats['success']} successful, {stats['skipped']} skipped, {stats['failed']} failed")
        
        if failed_files:
            print(f"\nFailed files ({len(failed_files)}):")
            for i, failed_file in enumerate(failed_files[:5]):  # Show first 5
                print(f"  {i+1}. {Path(failed_file).name}")
            if len(failed_files) > 5:
                print(f"  ... and {len(failed_files) - 5} more (check log file)")
        
        stats['failed_files'] = failed_files
        return stats

def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="Advanced Video File Converter")
    
    parser.add_argument('source_dir', help='Directory to search for video files')
    parser.add_argument('-o', '--output-dir', help='Output directory (default: source_dir/converted)')
    parser.add_argument('--no-skip-existing', action='store_true', help='Re-convert existing files')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose logging')
    
    args = parser.parse_args()
    
    # Setup logging
    logger = setup_logging(args.verbose)
    
    # Validate source directory
    source_path = Path(args.source_dir)
    if not source_path.exists():
        print(f"Error: Source directory not found: {args.source_dir}")
        sys.exit(1)
    
    # Create converter instance
    converter = VideoConverter(
        source_dir=args.source_dir,
        output_dir=args.output_dir,
        skip_existing=not args.no_skip_existing
    )
    
    try:
        # Run conversion
        stats = converter.convert_all()
        
        if 'error' in stats:
            print(f"Error: {stats['error']}")
            sys.exit(1)
        
        # Exit with error code if conversions failed
        if stats['failed'] > 0:
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\nGoodbye!")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        print(f"Unexpected error occurred. Check log file for details.")
        sys.exit(1)

if __name__ == "__main__":
    main()
