CC ?= cc
CFLAGS ?= -O2 -g -Wall -Wextra -fPIC
CPPFLAGS += -I/usr/include/sane
LDFLAGS += -shared -Wl,-soname,libsane-ar206.so.1
LIBS = -lsane -lusb-1.0

LIB = libsane-ar206.so.1.0.0

# Where the SANE dll loader looks for backends.  Debian/Ubuntu use a
# multiarch path (/usr/lib/<triplet>/sane); Alpine and most other distros
# use /usr/lib/sane.  Override on the command line if your layout differs:
#   make SANE_LIBDIR=/some/other/sane
SANE_LIBDIR ?= $(shell \
	if command -v dpkg-architecture >/dev/null 2>&1; then \
		echo /usr/lib/$$(dpkg-architecture -qDEB_HOST_MULTIARCH)/sane; \
	elif command -v cc >/dev/null 2>&1 && [ -n "$$(cc -print-multiarch 2>/dev/null)" ] \
	     && [ -d "/usr/lib/$$(cc -print-multiarch 2>/dev/null)/sane" ]; then \
		echo /usr/lib/$$(cc -print-multiarch 2>/dev/null)/sane; \
	else \
		echo /usr/lib/sane; \
	fi)

SANE_CONFDIR ?= /etc/sane.d
UDEV_RULESDIR ?= /etc/udev/rules.d

all: $(LIB)

$(LIB): ar206.c
	$(CC) $(CPPFLAGS) $(CFLAGS) $(LDFLAGS) -o $@ $< $(LIBS)
	ln -sf $(LIB) libsane-ar206.so.1
	ln -sf $(LIB) libsane-ar206.so

clean:
	rm -f $(LIB) libsane-ar206.so.1 libsane-ar206.so

install: $(LIB)
	install -d $(DESTDIR)$(SANE_LIBDIR)
	install -m 755 $(LIB) $(DESTDIR)$(SANE_LIBDIR)/$(LIB)
	ln -sf $(LIB) $(DESTDIR)$(SANE_LIBDIR)/libsane-ar206.so.1
	ln -sf $(LIB) $(DESTDIR)$(SANE_LIBDIR)/libsane-ar206.so
	install -m 644 ar206.conf $(DESTDIR)$(SANE_CONFDIR)/ar206.conf
	install -d $(DESTDIR)$(SANE_CONFDIR)/dll.d
	install -m 644 ar206.dll $(DESTDIR)$(SANE_CONFDIR)/dll.d/ar206
	@echo "installed backend to $(DESTDIR)$(SANE_LIBDIR)"

# Debian/Ubuntu: grant the scanner group access to the 132b:232b node so
# an unprivileged saned (or a user in the scanner group) can open it.
install-udev:
	install -d $(DESTDIR)$(UDEV_RULESDIR)
	install -m 644 60-ar206.rules $(DESTDIR)$(UDEV_RULESDIR)/60-ar206.rules
	@echo "installed udev rule; run: sudo udevadm control --reload && sudo udevadm trigger"

uninstall:
	rm -f $(DESTDIR)$(SANE_LIBDIR)/$(LIB)
	rm -f $(DESTDIR)$(SANE_LIBDIR)/libsane-ar206.so.1
	rm -f $(DESTDIR)$(SANE_LIBDIR)/libsane-ar206.so
	rm -f $(DESTDIR)$(SANE_CONFDIR)/ar206.conf
	rm -f $(DESTDIR)$(SANE_CONFDIR)/dll.d/ar206

uninstall-udev:
	rm -f $(DESTDIR)$(UDEV_RULESDIR)/60-ar206.rules

.PHONY: all clean install install-udev uninstall uninstall-udev
