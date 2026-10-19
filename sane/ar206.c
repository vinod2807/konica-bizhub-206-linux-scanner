/*
 * Minimal SANE backend for the Konica Minolta bizhub 206 USB scanner.
 *
 * The device speaks the AR206.DS command set on interface 0:
 *   EP 0x03  command OUT
 *   EP 0x85  response/image IN
 *
 * A scan is:
 *   status      03 0d 0a
 *   params      03 0c 0d 00 00 00 + 13 bytes
 *   geometry    03 0b 08
 *   init        03 09 01
 *   length      03 08 04 00 00 00 + LE32 + 01   (starts the scan)
 *   read chunk  03 0e 04 00 00 00 + LE32
 *
 * The 5-byte read header and the payload both arrive on 0x85.  Commands
 * 0x0a (abort) and 0x11 01 (session close) are deliberately not sent: the
 * former stops a scan, the latter wedges the bulk endpoints on this unit.
 *
 * This backend buffers one complete page in sane_start(), converts the
 * 1-bit data to 8-bit grayscale, rotates it, and serves it to the frontend
 * from sane_read().  It opens interface 0 only and never touches interface
 * 1 (usblp/printing).
 */

#include <sane/sane.h>
#include <sane/saneopts.h>

#include <libusb-1.0/libusb.h>

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/*
 * The SANE dll loader looks for per-backend symbols such as
 * _sane_ar206_init.  Normally sanei_backend.h provides these aliases; it
 * is not shipped in Alpine's sane-dev, so define them here.
 */
#define BACKEND_NAME ar206
#define sane_init _sane_ar206_init
#define sane_exit _sane_ar206_exit
#define sane_get_devices _sane_ar206_get_devices
#define sane_open _sane_ar206_open
#define sane_close _sane_ar206_close
#define sane_get_option_descriptor _sane_ar206_get_option_descriptor
#define sane_control_option _sane_ar206_control_option
#define sane_get_parameters _sane_ar206_get_parameters
#define sane_start _sane_ar206_start
#define sane_read _sane_ar206_read
#define sane_cancel _sane_ar206_cancel
#define sane_set_io_mode _sane_ar206_set_io_mode
#define sane_get_select_fd _sane_ar206_get_select_fd

#define AR206_VID 0x132b
#define AR206_PID 0x232b
#define EP_OUT 0x03
#define EP_IN 0x85
#define CMD_SIZE 64
#define MAX_CHUNK 65024

#define USB_TIMEOUT 15000
#define USB_TIMEOUT_FIRST 30000

enum
{
  OPT_NUM_OPTIONS = 0,
  OPT_RESOLUTION,
  OPT_MODE,
  OPT_SOURCE,
  OPT_PAPER,
  OPT_ROTATION,
  OPT_PREVIEW,
  NUM_OPTIONS
};

enum
{
  MODE_GRAY = 0,
  MODE_LINEART = 1
};

enum
{
  SOURCE_FLATBED = 0,
  SOURCE_ADF = 1
};

enum
{
  PAPER_A4 = 0,
  PAPER_A3 = 1
};

typedef struct
{
  SANE_Int resolution;
  SANE_Int mode;
  SANE_Int source;
  SANE_Int paper;
  SANE_Int rotation;           /* clockwise: 0, 90, 180, 270 */
  SANE_Bool preview;

  uint8_t *buf;
  size_t buf_len;
  size_t offset;
  SANE_Bool active;

  SANE_Bool have_params;
  SANE_Int params_w;
  SANE_Int params_h;
} Ar206_Handle;

static const char *device_name = "ar206:usb:132b:232b";
static int debug_enabled = 0;

#define DBG(...)                                                        \
  do                                                                    \
    {                                                                   \
      if (debug_enabled)                                                \
        fprintf (stderr, "ar206: " __VA_ARGS__);                        \
    }                                                                   \
  while (0)

static void
msleep (long ms)
{
  struct timespec ts;
  ts.tv_sec = ms / 1000;
  ts.tv_nsec = (ms % 1000) * 1000000L;
  nanosleep (&ts, NULL);
}

static const SANE_Word resolution_list[] = { 3, 150, 300, 600 };
static const SANE_String_Const mode_list[] = { "Gray", "Lineart", NULL };
static const SANE_String_Const source_list[] = { "Flatbed", "ADF", NULL };
static const SANE_String_Const paper_list[] = { "A4", "A3", NULL };
static const SANE_Range rotation_range = { 0, 270, 90 };

static const SANE_Option_Descriptor option_descriptors[NUM_OPTIONS] = {
  {
    .name = SANE_NAME_NUM_OPTIONS,
    .title = SANE_TITLE_NUM_OPTIONS,
    .desc = SANE_DESC_NUM_OPTIONS,
    .type = SANE_TYPE_INT,
    .unit = SANE_UNIT_NONE,
    .size = sizeof (SANE_Int),
    .cap = SANE_CAP_SOFT_DETECT,
    .constraint_type = SANE_CONSTRAINT_NONE,
    .constraint = { .string_list = NULL }
  },
  {
    .name = SANE_NAME_SCAN_RESOLUTION,
    .title = SANE_TITLE_SCAN_RESOLUTION,
    .desc = SANE_DESC_SCAN_RESOLUTION,
    .type = SANE_TYPE_INT,
    .unit = SANE_UNIT_DPI,
    .size = sizeof (SANE_Int),
    .cap = SANE_CAP_SOFT_SELECT | SANE_CAP_SOFT_DETECT,
    .constraint_type = SANE_CONSTRAINT_WORD_LIST,
    .constraint = { .word_list = resolution_list }
  },
  {
    .name = SANE_NAME_SCAN_MODE,
    .title = SANE_TITLE_SCAN_MODE,
    .desc = SANE_DESC_SCAN_MODE,
    .type = SANE_TYPE_STRING,
    .unit = SANE_UNIT_NONE,
    .size = 16,
    .cap = SANE_CAP_SOFT_SELECT | SANE_CAP_SOFT_DETECT,
    .constraint_type = SANE_CONSTRAINT_STRING_LIST,
    .constraint = { .string_list = mode_list }
  },
  {
    .name = SANE_NAME_SCAN_SOURCE,
    .title = SANE_TITLE_SCAN_SOURCE,
    .desc = SANE_DESC_SCAN_SOURCE,
    .type = SANE_TYPE_STRING,
    .unit = SANE_UNIT_NONE,
    .size = 16,
    .cap = SANE_CAP_SOFT_SELECT | SANE_CAP_SOFT_DETECT,
    .constraint_type = SANE_CONSTRAINT_STRING_LIST,
    .constraint = { .string_list = source_list }
  },
  {
    .name = "paper",
    .title = "Paper size",
    .desc = "Fixed scan area: A4 or A3.",
    .type = SANE_TYPE_STRING,
    .unit = SANE_UNIT_NONE,
    .size = 8,
    .cap = SANE_CAP_SOFT_SELECT | SANE_CAP_SOFT_DETECT,
    .constraint_type = SANE_CONSTRAINT_STRING_LIST,
    .constraint = { .string_list = paper_list }
  },
  {
    .name = "rotation",
    .title = "Rotation",
    .desc = "Rotate the output clockwise.  Flatbed defaults to 90, ADF to 270.",
    .type = SANE_TYPE_INT,
    .unit = SANE_UNIT_NONE,
    .size = sizeof (SANE_Int),
    .cap = SANE_CAP_SOFT_SELECT | SANE_CAP_SOFT_DETECT,
    .constraint_type = SANE_CONSTRAINT_RANGE,
    .constraint = { .range = &rotation_range }
  },
  {
    .name = SANE_NAME_PREVIEW,
    .title = SANE_TITLE_PREVIEW,
    .desc = SANE_DESC_PREVIEW,
    .type = SANE_TYPE_BOOL,
    .unit = SANE_UNIT_NONE,
    .size = sizeof (SANE_Bool),
    .cap = SANE_CAP_SOFT_SELECT | SANE_CAP_SOFT_DETECT,
    .constraint_type = SANE_CONSTRAINT_NONE,
    .constraint = { .string_list = NULL }
  }
};

static const SANE_Device ar206_device = {
  "ar206:usb:132b:232b",
  "KONICA MINOLTA",
  "bizhub 206",
  "flatbed scanner"
};

static const SANE_Device *device_list[] = { &ar206_device, NULL };
static const SANE_Device *empty_device_list[] = { NULL };

static int
string_index (const SANE_String_Const *list, const char *value)
{
  int i;
  if (value == NULL)
    return -1;
  for (i = 0; list[i] != NULL; i++)
    if (strcmp (list[i], value) == 0)
      return i;
  return -1;
}

static void
set_string (void *value, SANE_Int size, const char *text)
{
  char *dst = (char *) value;
  if (size <= 0)
    return;
  strncpy (dst, text, (size_t) size - 1);
  dst[size - 1] = '\0';
}

static int
device_present (void)
{
  libusb_context *ctx = NULL;
  libusb_device_handle *dev;
  int present = 0;

  if (libusb_init (&ctx) < 0)
    return 0;
  dev = libusb_open_device_with_vid_pid (ctx, AR206_VID, AR206_PID);
  if (dev != NULL)
    {
      present = 1;
      libusb_close (dev);
    }
  libusb_exit (ctx);
  return present;
}

static int
write_cmd (libusb_device_handle *dev, const uint8_t *data, int len)
{
  uint8_t buf[CMD_SIZE];
  int transferred = 0;
  int r;

  if (len <= 0 || len > CMD_SIZE)
    return -1;
  memset (buf, 0, sizeof (buf));
  memcpy (buf, data, (size_t) len);
  r = libusb_bulk_transfer (dev, EP_OUT, buf, CMD_SIZE, &transferred, 5000);
  if (r != 0 || transferred != CMD_SIZE)
    {
      DBG ("write failed: %s, transferred=%d\n",
           libusb_error_name (r), transferred);
      return -1;
    }
  return 0;
}

static int
read_exact (libusb_device_handle *dev, uint8_t *buf, int len, int timeout_ms)
{
  int got = 0;

  while (got < len)
    {
      int transferred = 0;
      int r = libusb_bulk_transfer (dev, EP_IN, buf + got, len - got,
                                    &transferred, timeout_ms);
      if (r != 0)
        {
          DBG ("read failed: %s at %d/%d\n", libusb_error_name (r),
               got, len);
          return -1;
        }
      if (transferred <= 0)
        {
          DBG ("short read at %d/%d\n", got, len);
          return -1;
        }
      got += transferred;
    }
  return 0;
}

static void
put_le32 (uint8_t *p, uint32_t value)
{
  p[0] = value & 0xff;
  p[1] = (value >> 8) & 0xff;
  p[2] = (value >> 16) & 0xff;
  p[3] = (value >> 24) & 0xff;
}

static void
convert_page (const uint8_t *raw, int row_bytes, int width, int height,
              int rotation, uint8_t *out, int out_width, int out_height)
{
  int sx, sy;

  (void) out_height;

  for (sy = 0; sy < height; sy++)
    {
      const uint8_t *row = raw + (size_t) sy * row_bytes;
      for (sx = 0; sx < width; sx++)
        {
          uint8_t value = (row[sx >> 3] & (0x80 >> (sx & 7))) ? 0 : 255;
          int dx, dy;

          switch (rotation)
            {
            case 90:
              dx = height - 1 - sy;
              dy = sx;
              break;
            case 180:
              dx = width - 1 - sx;
              dy = height - 1 - sy;
              break;
            case 270:
              dx = sy;
              dy = width - 1 - sx;
              break;
            case 0:
            default:
              dx = sx;
              dy = sy;
              break;
            }
          out[(size_t) dy * out_width + dx] = value;
        }
    }
}

static SANE_Status
do_scan (Ar206_Handle *h)
{
  libusb_context *ctx = NULL;
  libusb_device_handle *dev = NULL;
  SANE_Status status = SANE_STATUS_IO_ERROR;
  int claimed = 0;
  uint8_t status_data[10];
  uint8_t geom[8];
  uint8_t init = 0xff;
  uint8_t cmd[CMD_SIZE];
  uint8_t *raw = NULL;
  uint8_t *out = NULL;
  int line_width, height, win_width, win_height;
  int row_bytes;
  int dpi_code, paper_code;
  int win_w_600, win_h_600;
  uint32_t image_len;
  int got;
  int first_chunk = 1;
  int out_width, out_height;

  memset (status_data, 0, sizeof (status_data));
  memset (geom, 0, sizeof (geom));

  if (libusb_init (&ctx) < 0)
    {
      DBG ("libusb_init failed\n");
      return SANE_STATUS_IO_ERROR;
    }
  dev = libusb_open_device_with_vid_pid (ctx, AR206_VID, AR206_PID);
  if (dev == NULL)
    {
      DBG ("device not found or access denied\n");
      status = SANE_STATUS_DEVICE_BUSY;
      goto cleanup;
    }

  libusb_set_auto_detach_kernel_driver (dev, 1);
  {
    int r = libusb_claim_interface (dev, 0);
    if (r != 0)
      {
        DBG ("claim interface 0 failed: %s\n", libusb_error_name (r));
        status = (r == LIBUSB_ERROR_BUSY) ? SANE_STATUS_DEVICE_BUSY
                                          : SANE_STATUS_IO_ERROR;
        goto cleanup;
      }
    claimed = 1;
  }

  /* Status. */
  memset (cmd, 0, sizeof (cmd));
  cmd[0] = 0x03;
  cmd[1] = 0x0d;
  cmd[2] = 0x0a;
  if (write_cmd (dev, cmd, 3) != 0
      || read_exact (dev, status_data, 10, USB_TIMEOUT) != 0)
    goto cleanup;

  DBG ("status: %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x\n",
       status_data[0], status_data[1], status_data[2], status_data[3],
       status_data[4], status_data[5], status_data[6], status_data[7],
       status_data[8], status_data[9]);

  if (h->source == SOURCE_ADF && (status_data[1] & 1) == 0)
    {
      status = SANE_STATUS_NO_DOCS;
      goto cleanup;
    }

  switch (h->paper)
    {
    case PAPER_A3:
      paper_code = 0;
      win_w_600 = 7015;
      win_h_600 = 9921;
      break;
    case PAPER_A4:
    default:
      paper_code = 2;
      win_w_600 = 4960;
      win_h_600 = 7015;
      break;
    }

  switch (h->resolution)
    {
    case 150:
      dpi_code = 0;
      break;
    case 600:
      dpi_code = 2;
      break;
    case 300:
    default:
      dpi_code = 1;
      break;
    }

  /* Parameter block. */
  memset (cmd, 0, sizeof (cmd));
  cmd[0] = 0x03;
  cmd[1] = 0x0c;
  cmd[2] = 0x0d;
  cmd[3] = 0x00;
  cmd[4] = 0x00;
  cmd[5] = 0x00;
  cmd[6] = (uint8_t) dpi_code;
  cmd[7] = 0;                   /* mono */
  cmd[8] = 5;
  cmd[9] = (uint8_t) paper_code;
  cmd[14] = win_w_600 & 0xff;
  cmd[15] = (win_w_600 >> 8) & 0xff;
  cmd[16] = win_h_600 & 0xff;
  cmd[17] = (win_h_600 >> 8) & 0xff;
  cmd[18] = (h->source == SOURCE_ADF) ? 2 : 0;
  if (write_cmd (dev, cmd, 19) != 0)
    goto cleanup;
  msleep (50);

  /* Geometry. */
  memset (cmd, 0, sizeof (cmd));
  cmd[0] = 0x03;
  cmd[1] = 0x0b;
  cmd[2] = 0x08;
  if (write_cmd (dev, cmd, 3) != 0
      || read_exact (dev, geom, 8, USB_TIMEOUT) != 0)
    goto cleanup;

  line_width = geom[0] | (geom[1] << 8);
  height = geom[2] | (geom[3] << 8);
  win_width = geom[4] | (geom[5] << 8);
  win_height = geom[6] | (geom[7] << 8);
  DBG ("geometry: line=%d height=%d window=%dx%d\n",
       line_width, height, win_width, win_height);
  if (line_width <= 0 || height <= 0 || win_width <= 0 || win_height <= 0)
    {
      DBG ("parameter block rejected\n");
      status = SANE_STATUS_INVAL;
      goto cleanup;
    }

  /* Init. */
  memset (cmd, 0, sizeof (cmd));
  cmd[0] = 0x03;
  cmd[1] = 0x09;
  cmd[2] = 0x01;
  if (write_cmd (dev, cmd, 3) != 0
      || read_exact (dev, &init, 1, USB_TIMEOUT) != 0)
    goto cleanup;
  if (init != 0)
    {
      DBG ("init failed: %02x\n", init);
      status = SANE_STATUS_IO_ERROR;
      goto cleanup;
    }

  row_bytes = (line_width + 7) / 8;
  image_len = (uint32_t) row_bytes * (uint32_t) height;
  DBG ("image: %d bytes/row x %d = %u bytes\n",
       row_bytes, height, image_len);

  /* Set length; the trailing 0x01 starts the scan. */
  memset (cmd, 0, sizeof (cmd));
  cmd[0] = 0x03;
  cmd[1] = 0x08;
  cmd[2] = 0x04;
  cmd[3] = 0x00;
  cmd[4] = 0x00;
  cmd[5] = 0x00;
  put_le32 (cmd + 6, image_len);
  cmd[10] = 0x01;
  if (write_cmd (dev, cmd, 11) != 0)
    goto cleanup;
  msleep (800);

  raw = (uint8_t *) malloc (image_len);
  if (raw == NULL)
    {
      status = SANE_STATUS_NO_MEM;
      goto cleanup;
    }

  got = 0;
  while ((uint32_t) got < image_len)
    {
      uint32_t want = image_len - (uint32_t) got;
      uint8_t hdr[5];
      uint32_t avail, take;

      if (want > MAX_CHUNK)
        want = MAX_CHUNK;

      memset (cmd, 0, sizeof (cmd));
      cmd[0] = 0x03;
      cmd[1] = 0x0e;
      cmd[2] = 0x04;
      cmd[3] = 0x00;
      cmd[4] = 0x00;
      cmd[5] = 0x00;
      put_le32 (cmd + 6, want);
      if (write_cmd (dev, cmd, 10) != 0)
        goto cleanup;

      if (read_exact (dev, hdr, 5,
                      first_chunk ? USB_TIMEOUT_FIRST : USB_TIMEOUT) != 0)
        goto cleanup;
      first_chunk = 0;
      if (hdr[0] != 0)
        {
          DBG ("chunk status %02x\n", hdr[0]);
          status = SANE_STATUS_IO_ERROR;
          goto cleanup;
        }
      avail = (uint32_t) hdr[1] | ((uint32_t) hdr[2] << 8);
      if (avail == 0)
        break;
      take = avail;
      if (take > image_len - (uint32_t) got)
        take = image_len - (uint32_t) got;
      if (read_exact (dev, raw + got, (int) take, USB_TIMEOUT) != 0)
        goto cleanup;
      got += (int) take;
    }

  if ((uint32_t) got != image_len)
    {
      DBG ("short image: %d of %u bytes\n", got, image_len);
      status = SANE_STATUS_IO_ERROR;
      goto cleanup;
    }

  out_width = (h->rotation == 90 || h->rotation == 270)
              ? height : win_width;
  out_height = (h->rotation == 90 || h->rotation == 270)
               ? win_width : height;
  out = (uint8_t *) malloc ((size_t) out_width * (size_t) out_height);
  if (out == NULL)
    {
      status = SANE_STATUS_NO_MEM;
      goto cleanup;
    }

  convert_page (raw, row_bytes, win_width, height, h->rotation,
                out, out_width, out_height);
  free (raw);
  raw = NULL;

  free (h->buf);
  h->buf = out;
  h->buf_len = (size_t) out_width * (size_t) out_height;
  h->offset = 0;
  h->active = SANE_TRUE;
  h->have_params = SANE_TRUE;
  h->params_w = out_width;
  h->params_h = out_height;
  out = NULL;
  status = SANE_STATUS_GOOD;

cleanup:
  free (raw);
  free (out);
  if (dev != NULL)
    {
      if (claimed)
        libusb_release_interface (dev, 0);
      libusb_close (dev);
    }
  if (ctx != NULL)
    libusb_exit (ctx);
  return status;
}

SANE_Status
sane_init (SANE_Int *version_code, SANE_Auth_Callback authorize)
{
  (void) authorize;
  debug_enabled = (getenv ("AR206_DEBUG") != NULL) ? 1 : 0;
  if (version_code != NULL)
    *version_code = SANE_VERSION_CODE (SANE_CURRENT_MAJOR,
                                      SANE_CURRENT_MINOR, 0);
  return SANE_STATUS_GOOD;
}

void
sane_exit (void)
{
}

SANE_Status
sane_get_devices (const SANE_Device ***device_list_out, SANE_Bool local_only)
{
  (void) local_only;
  if (device_list_out == NULL)
    return SANE_STATUS_INVAL;
  *device_list_out = device_present () ? device_list : empty_device_list;
  return SANE_STATUS_GOOD;
}

SANE_Status
sane_open (SANE_String_Const devicename, SANE_Handle *handle)
{
  Ar206_Handle *h;

  if (handle == NULL)
    return SANE_STATUS_INVAL;
  *handle = NULL;
  if (devicename != NULL && strcmp (devicename, device_name) != 0
      && strcmp (devicename, "ar206") != 0)
    return SANE_STATUS_INVAL;
  if (!device_present ())
    return SANE_STATUS_INVAL;

  h = (Ar206_Handle *) calloc (1, sizeof (*h));
  if (h == NULL)
    return SANE_STATUS_NO_MEM;
  h->resolution = 300;
  h->mode = MODE_GRAY;
  h->source = SOURCE_FLATBED;
  h->paper = PAPER_A4;
  h->rotation = 90;
  h->preview = SANE_FALSE;
  h->active = SANE_FALSE;
  h->have_params = SANE_FALSE;
  *handle = (SANE_Handle) h;
  return SANE_STATUS_GOOD;
}

void
sane_close (SANE_Handle handle)
{
  Ar206_Handle *h = (Ar206_Handle *) handle;
  if (h == NULL)
    return;
  free (h->buf);
  free (h);
}

const SANE_Option_Descriptor *
sane_get_option_descriptor (SANE_Handle handle, SANE_Int option)
{
  (void) handle;
  if (option < 0 || option >= NUM_OPTIONS)
    return NULL;
  return &option_descriptors[option];
}

SANE_Status
sane_control_option (SANE_Handle handle, SANE_Int option, SANE_Action action,
                     void *value, SANE_Int *info)
{
  Ar206_Handle *h = (Ar206_Handle *) handle;
  const SANE_Option_Descriptor *desc;
  int index;

  if (h == NULL || option < 0 || option >= NUM_OPTIONS)
    return SANE_STATUS_INVAL;
  if (info != NULL)
    *info = 0;
  desc = &option_descriptors[option];

  if (action == SANE_ACTION_SET_AUTO)
    return SANE_STATUS_UNSUPPORTED;
  if (action == SANE_ACTION_SET_VALUE && !SANE_OPTION_IS_SETTABLE (desc->cap))
    return SANE_STATUS_INVAL;

  if (action == SANE_ACTION_GET_VALUE)
    {
      if (value == NULL)
        return SANE_STATUS_INVAL;
      switch (option)
        {
        case OPT_NUM_OPTIONS:
          *(SANE_Int *) value = NUM_OPTIONS;
          return SANE_STATUS_GOOD;
        case OPT_RESOLUTION:
          *(SANE_Int *) value = h->resolution;
          return SANE_STATUS_GOOD;
        case OPT_MODE:
          set_string (value, desc->size, mode_list[h->mode]);
          return SANE_STATUS_GOOD;
        case OPT_SOURCE:
          set_string (value, desc->size, source_list[h->source]);
          return SANE_STATUS_GOOD;
        case OPT_PAPER:
          set_string (value, desc->size, paper_list[h->paper]);
          return SANE_STATUS_GOOD;
        case OPT_ROTATION:
          *(SANE_Int *) value = h->rotation;
          return SANE_STATUS_GOOD;
        case OPT_PREVIEW:
          *(SANE_Bool *) value = h->preview;
          return SANE_STATUS_GOOD;
        default:
          return SANE_STATUS_INVAL;
        }
    }

  /* SET_VALUE */
  if (value == NULL)
    return SANE_STATUS_INVAL;

  switch (option)
    {
    case OPT_RESOLUTION:
      {
        SANE_Int v = *(SANE_Int *) value;
        if (v != 150 && v != 300 && v != 600)
          return SANE_STATUS_INVAL;
        h->resolution = v;
        h->have_params = SANE_FALSE;
        if (info != NULL)
          *info |= SANE_INFO_RELOAD_PARAMS;
        return SANE_STATUS_GOOD;
      }
    case OPT_MODE:
      index = string_index (mode_list, (const char *) value);
      if (index < 0)
        return SANE_STATUS_INVAL;
      h->mode = index;
      return SANE_STATUS_GOOD;
    case OPT_SOURCE:
      index = string_index (source_list, (const char *) value);
      if (index < 0)
        return SANE_STATUS_INVAL;
      h->source = index;
      h->rotation = (index == SOURCE_ADF) ? 270 : 90;
      h->have_params = SANE_FALSE;
      if (info != NULL)
        *info |= SANE_INFO_RELOAD_OPTIONS | SANE_INFO_RELOAD_PARAMS;
      return SANE_STATUS_GOOD;
    case OPT_PAPER:
      index = string_index (paper_list, (const char *) value);
      if (index < 0)
        return SANE_STATUS_INVAL;
      h->paper = index;
      h->have_params = SANE_FALSE;
      if (info != NULL)
        *info |= SANE_INFO_RELOAD_PARAMS;
      return SANE_STATUS_GOOD;
    case OPT_ROTATION:
      index = *(SANE_Int *) value;
      if (index != 0 && index != 90 && index != 180 && index != 270)
        return SANE_STATUS_INVAL;
      h->rotation = index;
      h->have_params = SANE_FALSE;
      if (info != NULL)
        *info |= SANE_INFO_RELOAD_PARAMS;
      return SANE_STATUS_GOOD;
    case OPT_PREVIEW:
      h->preview = *(SANE_Bool *) value ? SANE_TRUE : SANE_FALSE;
      return SANE_STATUS_GOOD;
    default:
      return SANE_STATUS_INVAL;
    }
}

static void
computed_size (const Ar206_Handle *h, SANE_Int *width, SANE_Int *height)
{
  int w, ht;

  if (h->paper == PAPER_A3)
    {
      switch (h->resolution)
        {
        case 150:
          w = 1753;
          ht = 2480;
          break;
        case 600:
          w = 7015;
          ht = 9921;
          break;
        case 300:
        default:
          w = 3507;
          ht = 4960;
          break;
        }
    }
  else
    {
      switch (h->resolution)
        {
        case 150:
          w = 1240;
          ht = 1753;
          break;
        case 600:
          w = 4960;
          ht = 7015;
          break;
        case 300:
        default:
          w = 2480;
          ht = 3507;
          break;
        }
    }

  if (h->rotation == 90 || h->rotation == 270)
    {
      int tmp = w;
      w = ht;
      ht = tmp;
    }
  *width = w;
  *height = ht;
}

SANE_Status
sane_get_parameters (SANE_Handle handle, SANE_Parameters *params)
{
  Ar206_Handle *h = (Ar206_Handle *) handle;
  SANE_Int w, ht;

  if (h == NULL || params == NULL)
    return SANE_STATUS_INVAL;
  if (h->have_params)
    {
      w = h->params_w;
      ht = h->params_h;
    }
  else
    computed_size (h, &w, &ht);

  params->format = SANE_FRAME_GRAY;
  params->last_frame = SANE_TRUE;
  params->bytes_per_line = w;
  params->pixels_per_line = w;
  params->lines = ht;
  params->depth = 8;
  return SANE_STATUS_GOOD;
}

SANE_Status
sane_start (SANE_Handle handle)
{
  Ar206_Handle *h = (Ar206_Handle *) handle;
  SANE_Status status;

  if (h == NULL)
    return SANE_STATUS_INVAL;
  if (h->active)
    return SANE_STATUS_DEVICE_BUSY;

  free (h->buf);
  h->buf = NULL;
  h->buf_len = 0;
  h->offset = 0;
  h->active = SANE_FALSE;
  h->have_params = SANE_FALSE;

  status = do_scan (h);
  if (status != SANE_STATUS_GOOD)
    return status;
  return SANE_STATUS_GOOD;
}

SANE_Status
sane_read (SANE_Handle handle, SANE_Byte *data, SANE_Int max_length,
           SANE_Int *length)
{
  Ar206_Handle *h = (Ar206_Handle *) handle;
  size_t remaining;
  size_t n;

  if (length != NULL)
    *length = 0;
  if (h == NULL || data == NULL || length == NULL || max_length < 0)
    return SANE_STATUS_INVAL;
  if (!h->active)
    return SANE_STATUS_INVAL;
  if (h->offset >= h->buf_len)
    return SANE_STATUS_EOF;

  remaining = h->buf_len - h->offset;
  n = (size_t) max_length;
  if (n > remaining)
    n = remaining;
  if (n > 0)
    {
      memcpy (data, h->buf + h->offset, n);
      h->offset += n;
    }
  *length = (SANE_Int) n;
  return SANE_STATUS_GOOD;
}

void
sane_cancel (SANE_Handle handle)
{
  Ar206_Handle *h = (Ar206_Handle *) handle;
  if (h == NULL)
    return;
  free (h->buf);
  h->buf = NULL;
  h->buf_len = 0;
  h->offset = 0;
  h->active = SANE_FALSE;
}

SANE_Status
sane_set_io_mode (SANE_Handle handle, SANE_Bool non_blocking)
{
  (void) handle;
  return non_blocking ? SANE_STATUS_UNSUPPORTED : SANE_STATUS_GOOD;
}

SANE_Status
sane_get_select_fd (SANE_Handle handle, SANE_Int *fd)
{
  (void) handle;
  (void) fd;
  return SANE_STATUS_UNSUPPORTED;
}

SANE_String_Const
sane_strstatus (SANE_Status status)
{
  switch (status)
    {
    case SANE_STATUS_GOOD:
      return "good";
    case SANE_STATUS_UNSUPPORTED:
      return "unsupported";
    case SANE_STATUS_CANCELLED:
      return "cancelled";
    case SANE_STATUS_DEVICE_BUSY:
      return "device busy";
    case SANE_STATUS_INVAL:
      return "invalid";
    case SANE_STATUS_EOF:
      return "end of file";
    case SANE_STATUS_JAMMED:
      return "jammed";
    case SANE_STATUS_NO_DOCS:
      return "no documents";
    case SANE_STATUS_COVER_OPEN:
      return "cover open";
    case SANE_STATUS_IO_ERROR:
      return "I/O error";
    case SANE_STATUS_NO_MEM:
      return "out of memory";
    case SANE_STATUS_ACCESS_DENIED:
      return "access denied";
    default:
      return "unknown";
    }
}
