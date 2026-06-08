import ctypes
import os
import numpy as np
from PIL import Image
from enum import IntEnum

# Load the shared library
lib_path = os.path.join(os.path.dirname(__file__), 'libisyntax.so')
libisyntax = ctypes.CDLL(lib_path)

# Define the error codes
class ErrorCode(IntEnum):
	OK = 0
	FATAL = 1
	INVALID_ARGUMENT = 2

# Define the pixel format enum
class ISyntaxPixelFormat(IntEnum):
	"""Pixel formats for libisyntax C API; libisyntax pixel format values start at 0x100 (256) as defined in the C API to namespace these codes"""
	RGBA = 0x100 + 1
	BGRA = 0x100 + 2

# Define the structures
class ISyntaxT(ctypes.Structure):
	_fields_ = [
		("ll_coeff_block_allocator", ctypes.POINTER(ctypes.c_void_p)),
		("h_coeff_block_allocator", ctypes.POINTER(ctypes.c_void_p)),
		("block_width", ctypes.c_int32),
		("block_height", ctypes.c_int32),
		("is_block_allocator_owned", ctypes.c_bool),
	]

class ISyntaxImageT(ctypes.Structure):
	pass

class ISyntaxLevelT(ctypes.Structure):
	pass

class ISyntaxCacheT(ctypes.Structure):
	_fields_ = [
		("ll_coeff_block_allocator", ctypes.POINTER(ctypes.c_void_p)),
		("h_coeff_block_allocator", ctypes.POINTER(ctypes.c_void_p)),
		("allocator_block_width", ctypes.c_int32),
		("allocator_block_height", ctypes.c_int32),
	]

# Define the function signatures
libisyntax.libisyntax_init.restype = ctypes.c_int32
libisyntax.libisyntax_open.argtypes = [ctypes.c_char_p, ctypes.c_int32, ctypes.POINTER(ctypes.POINTER(ISyntaxT))]
libisyntax.libisyntax_open.restype = ctypes.c_int32
libisyntax.libisyntax_close.argtypes = [ctypes.POINTER(ISyntaxT)]
libisyntax.libisyntax_close.restype = None

libisyntax.libisyntax_get_tile_width.argtypes = [ctypes.POINTER(ISyntaxT)]
libisyntax.libisyntax_get_tile_width.restype = ctypes.c_int32

libisyntax.libisyntax_get_tile_height.argtypes = [ctypes.POINTER(ISyntaxT)]
libisyntax.libisyntax_get_tile_height.restype = ctypes.c_int32

libisyntax.libisyntax_get_wsi_image.argtypes = [ctypes.POINTER(ISyntaxT)]
libisyntax.libisyntax_get_wsi_image.restype = ctypes.POINTER(ISyntaxImageT)

libisyntax.libisyntax_get_label_image.argtypes = [ctypes.POINTER(ISyntaxT)]
libisyntax.libisyntax_get_label_image.restype = ctypes.POINTER(ISyntaxImageT)

libisyntax.libisyntax_get_macro_image.argtypes = [ctypes.POINTER(ISyntaxT)]
libisyntax.libisyntax_get_macro_image.restype = ctypes.POINTER(ISyntaxImageT)

libisyntax.libisyntax_image_get_level_count.argtypes = [ctypes.POINTER(ISyntaxImageT)]
libisyntax.libisyntax_image_get_level_count.restype = ctypes.c_int32

libisyntax.libisyntax_image_get_level.argtypes = [ctypes.POINTER(ISyntaxImageT), ctypes.c_int32]
libisyntax.libisyntax_image_get_level.restype = ctypes.POINTER(ISyntaxLevelT)

libisyntax.libisyntax_level_get_scale.argtypes = [ctypes.POINTER(ISyntaxLevelT)]
libisyntax.libisyntax_level_get_scale.restype = ctypes.c_int32

libisyntax.libisyntax_level_get_width_in_tiles.argtypes = [ctypes.POINTER(ISyntaxLevelT)]
libisyntax.libisyntax_level_get_width_in_tiles.restype = ctypes.c_int32

libisyntax.libisyntax_level_get_height_in_tiles.argtypes = [ctypes.POINTER(ISyntaxLevelT)]
libisyntax.libisyntax_level_get_height_in_tiles.restype = ctypes.c_int32

libisyntax.libisyntax_level_get_width.argtypes = [ctypes.POINTER(ISyntaxLevelT)]
libisyntax.libisyntax_level_get_width.restype = ctypes.c_int32

libisyntax.libisyntax_level_get_height.argtypes = [ctypes.POINTER(ISyntaxLevelT)]
libisyntax.libisyntax_level_get_height.restype = ctypes.c_int32

libisyntax.libisyntax_level_get_mpp_x.argtypes = [ctypes.POINTER(ISyntaxLevelT)]
libisyntax.libisyntax_level_get_mpp_x.restype = ctypes.c_float

libisyntax.libisyntax_level_get_mpp_y.argtypes = [ctypes.POINTER(ISyntaxLevelT)]
libisyntax.libisyntax_level_get_mpp_y.restype = ctypes.c_float

libisyntax.libisyntax_cache_create.argtypes = [ctypes.c_char_p, ctypes.c_int32, ctypes.POINTER(ctypes.POINTER(ISyntaxCacheT))]
libisyntax.libisyntax_cache_create.restype = ctypes.c_int32

libisyntax.libisyntax_cache_inject.argtypes = [ctypes.POINTER(ISyntaxCacheT), ctypes.POINTER(ISyntaxT)]
libisyntax.libisyntax_cache_inject.restype = ctypes.c_int32

libisyntax.libisyntax_cache_destroy.argtypes = [ctypes.POINTER(ISyntaxCacheT)]
libisyntax.libisyntax_cache_destroy.restype = None

libisyntax.libisyntax_tile_read.argtypes = [ctypes.POINTER(ISyntaxT), ctypes.POINTER(ISyntaxCacheT), ctypes.c_int32, ctypes.c_int64, ctypes.c_int64, ctypes.POINTER(ctypes.c_uint32), ctypes.c_int32]
libisyntax.libisyntax_tile_read.restype = ctypes.c_int32

libisyntax.libisyntax_read_region.argtypes = [ctypes.POINTER(ISyntaxT), ctypes.POINTER(ISyntaxCacheT), ctypes.c_int32, ctypes.c_int64, ctypes.c_int64, ctypes.c_int64, ctypes.c_int64, ctypes.POINTER(ctypes.c_uint32), ctypes.c_int32]
libisyntax.libisyntax_read_region.restype = ctypes.c_int32

libisyntax.libisyntax_read_label_image.argtypes = [ctypes.POINTER(ISyntaxT), ctypes.POINTER(ctypes.c_int32), ctypes.POINTER(ctypes.c_int32), ctypes.POINTER(ctypes.POINTER(ctypes.c_uint32)), ctypes.c_int32]
libisyntax.libisyntax_read_label_image.restype = ctypes.c_int32

libisyntax.libisyntax_read_macro_image.argtypes = [ctypes.POINTER(ISyntaxT), ctypes.POINTER(ctypes.c_int32), ctypes.POINTER(ctypes.c_int32), ctypes.POINTER(ctypes.POINTER(ctypes.c_uint32)), ctypes.c_int32]
libisyntax.libisyntax_read_macro_image.restype = ctypes.c_int32

libisyntax.libisyntax_read_label_image_jpeg.argtypes = [ctypes.POINTER(ISyntaxT), ctypes.POINTER(ctypes.POINTER(ctypes.c_uint8)), ctypes.POINTER(ctypes.c_uint32)]
libisyntax.libisyntax_read_label_image_jpeg.restype = ctypes.c_int32

libisyntax.libisyntax_read_macro_image_jpeg.argtypes = [ctypes.POINTER(ISyntaxT), ctypes.POINTER(ctypes.POINTER(ctypes.c_uint8)), ctypes.POINTER(ctypes.c_uint32)]
libisyntax.libisyntax_read_macro_image_jpeg.restype = ctypes.c_int32

libisyntax.libisyntax_read_icc_profile.argtypes = [ctypes.POINTER(ISyntaxT), ctypes.POINTER(ISyntaxImageT), ctypes.POINTER(ctypes.POINTER(ctypes.c_uint8)), ctypes.POINTER(ctypes.c_uint32)]
libisyntax.libisyntax_read_icc_profile.restype = ctypes.c_int32

libisyntax.libisyntax_get_barcode.argtypes = [ctypes.POINTER(ISyntaxT)]
libisyntax.libisyntax_get_barcode.restype = ctypes.c_char_p

def buffer_to_array_or_image(region, width, height, pixel_format, return_pil_image=False) -> np.ndarray | Image.Image:
	# Convert ctypes array to numpy array
	buffer = np.ctypeslib.as_array(region)
	buffer = buffer.view(dtype=np.uint8)
	
	if pixel_format == ISyntaxPixelFormat.RGBA:
		# Reshape buffer to (height, width, 4) for RGBA format
		buffer = buffer.reshape((height, width, 4))
		mode = "RGBA"
	elif pixel_format == ISyntaxPixelFormat.BGRA:
		# Reshape buffer to (height, width, 4) for BGRA format
		buffer = buffer.reshape((height, width, 4))
		# Convert BGRA to RGBA
		buffer = buffer[:, :, [2, 1, 0, 3]]
		mode = "RGBA"
	else:
		raise ValueError("Unsupported pixel format")
	
	# Create a PIL Image from the numpy array
	if return_pil_image:
		image = Image.fromarray(buffer, mode=mode)
		return image
	else:
		# Convert to numpy array
		return buffer

# Define Python wrapper classes
class ISyntaxWSI:
	def __init__(self, filename, cache_size=1024*1024*512, pixel_format=ISyntaxPixelFormat.RGBA):
		# Initialize the library
		result = libisyntax.libisyntax_init()
		if result != ErrorCode.OK:
			raise RuntimeError(f"libisyntax_init failed with error code {result}")

		self.isyntax = ctypes.POINTER(ISyntaxT)()
		# Set is_init_allocators to 0
		result = libisyntax.libisyntax_open(filename.encode('utf-8'), 0, ctypes.byref(self.isyntax))
		if result != ErrorCode.OK:
			import traceback
			traceback.print_stack()
			raise RuntimeError(f"Error opening iSyntax file: {result}")
		
		self.cache_size = cache_size
		self.pixel_format = pixel_format
		# Create and inject a persistent cache for region reads
		self._cache = ISyntaxCache(debug_name_or_null=None, cache_size=self.cache_size)
		self._cache.inject(self)
		
	def close(self):
		libisyntax.libisyntax_close(self.isyntax)
		# Clean up cache
		self._cache.destroy()

	def __enter__(self):
		# Support use as a context manager
		return self

	def __exit__(self, exc_type, exc_val, exc_tb):
		# Ensure resources are cleaned up
		self.close()

	def get_tile_width(self):
		return libisyntax.libisyntax_get_tile_width(self.isyntax)

	def get_tile_height(self):
		return libisyntax.libisyntax_get_tile_height(self.isyntax)

	def get_level_width(self, level):
		level = libisyntax.libisyntax_image_get_level(self._get_wsi_image(), level)
		return libisyntax.libisyntax_level_get_width(level)
	
	def get_level_height(self, level):
		level = libisyntax.libisyntax_image_get_level(self._get_wsi_image(), level)
		return libisyntax.libisyntax_level_get_height(level)
	
	def get_level_mpp_x(self, level):
		level = libisyntax.libisyntax_image_get_level(self._get_wsi_image(), level)
		return libisyntax.libisyntax_level_get_mpp_x(level)
	
	def get_level_mpp_y(self, level):
		level = libisyntax.libisyntax_image_get_level(self._get_wsi_image(), level)
		return libisyntax.libisyntax_level_get_mpp_y(level)
	
	def get_level_count(self):
		return libisyntax.libisyntax_image_get_level_count(self._get_wsi_image())
	
	def _get_wsi_image(self):
		return libisyntax.libisyntax_get_wsi_image(self.isyntax)
	
	def get_barcode(self):
		result = libisyntax.libisyntax_get_barcode(self.isyntax)
		return result.decode("utf-8") if result else None

	def read_label_image(self, pixel_format=None, return_pil_image=False) -> np.ndarray | Image.Image:
		"""Read the label image (photograph of the slide's physical label).
		
		Note: libisyntax does not expose a function to free the pixel buffer it
		allocates for this call, so this leaks ~width*height*4 bytes per call.
		For typical label images (~100-500 KB), this is fine for occasional use
		but avoid calling in tight loops.
		"""
		if pixel_format is None:
			pixel_format = self.pixel_format
		
		width = ctypes.c_int32()
		height = ctypes.c_int32()
		pixels_buffer = ctypes.POINTER(ctypes.c_uint32)()
		result = libisyntax.libisyntax_read_label_image(
			self.isyntax, ctypes.byref(width), ctypes.byref(height),
			ctypes.byref(pixels_buffer), pixel_format.value
		)
		if result != ErrorCode.OK:
			raise RuntimeError(f"Error reading label image: {result}")
		
		# Convert the unsized pointer into a sized ctypes array so numpy can reshape it
		sized_buffer = ctypes.cast(
			pixels_buffer,
			ctypes.POINTER(ctypes.c_uint32 * (width.value * height.value))
		).contents
		
		result_image = buffer_to_array_or_image(
			sized_buffer, width.value, height.value, pixel_format, return_pil_image
		)
		
		# Copy so the returned data is independent of the (leaked) C buffer
		return result_image.copy()

	def read_macro_image(self, pixel_format=None, return_pil_image=False) -> np.ndarray | Image.Image:
		"""Read the macro image (low-res overview photograph of the whole slide).
		
		Note: libisyntax does not expose a function to free the pixel buffer it
		allocates for this call, so this leaks ~width*height*4 bytes per call.
		For typical macro images, this is fine for occasional use but avoid
		calling in tight loops.
		"""
		if pixel_format is None:
			pixel_format = self.pixel_format
		
		width = ctypes.c_int32()
		height = ctypes.c_int32()
		pixels_buffer = ctypes.POINTER(ctypes.c_uint32)()
		result = libisyntax.libisyntax_read_macro_image(
			self.isyntax, ctypes.byref(width), ctypes.byref(height),
			ctypes.byref(pixels_buffer), pixel_format.value
		)
		if result != ErrorCode.OK:
			raise RuntimeError(f"Error reading macro image: {result}")
		
		sized_buffer = ctypes.cast(
			pixels_buffer,
			ctypes.POINTER(ctypes.c_uint32 * (width.value * height.value))
		).contents
		
		result_image = buffer_to_array_or_image(
			sized_buffer, width.value, height.value, pixel_format, return_pil_image
		)
		
		return result_image.copy()

	def read_label_image_jpeg_bytes(self) -> bytes:
		"""Read the label image as its original embedded JPEG bytes.
		
		This avoids re-encoding and often gives better quality than
		read_label_image() for OCR purposes.
		"""
		jpeg_buffer = ctypes.POINTER(ctypes.c_uint8)()
		jpeg_size = ctypes.c_uint32()
		
		result = libisyntax.libisyntax_read_label_image_jpeg(
			self.isyntax, ctypes.byref(jpeg_buffer), ctypes.byref(jpeg_size)
		)
		if result != ErrorCode.OK:
			raise RuntimeError(f"Error reading label JPEG: {result}")
		
		size = jpeg_size.value
		jpeg_bytes = bytes(
			ctypes.cast(
				jpeg_buffer, ctypes.POINTER(ctypes.c_uint8 * size)
			).contents
		)
		return jpeg_bytes

	def save_label_jpeg(self, output_path: str) -> str:
		"""Save the label as its native JPEG."""
		with open(output_path, "wb") as f:
			f.write(self.read_label_image_jpeg_bytes())
		return output_path

	def read_region(self, level, x, y, width, height, return_pil_image=False) -> np.ndarray | Image.Image:
		pixels_buffer = (ctypes.c_uint32 * (width * height))()
		result = libisyntax.libisyntax_read_region(
			self.isyntax, self._cache.cache, level, x, y, width, height, pixels_buffer, self.pixel_format.value
		)
		if result != ErrorCode.OK:
			raise RuntimeError(f"Error reading region: {result}")
		
		return buffer_to_array_or_image(pixels_buffer, width, height, self.pixel_format, return_pil_image)

class ISyntaxCache:
	def __init__(self, debug_name_or_null, cache_size):
		self.cache = ctypes.POINTER(ISyntaxCacheT)()
		result = libisyntax.libisyntax_cache_create(debug_name_or_null.encode('utf-8') if debug_name_or_null else None, cache_size, ctypes.byref(self.cache))
		if result != ErrorCode.OK:
			raise RuntimeError(f"Error creating cache: {result}")

	def inject(self, isyntax):
		result = libisyntax.libisyntax_cache_inject(self.cache, isyntax.isyntax)
		if result != ErrorCode.OK:
			raise RuntimeError(f"Error injecting isyntax into cache: {result}")

	def destroy(self):
		libisyntax.libisyntax_cache_destroy(self.cache)
