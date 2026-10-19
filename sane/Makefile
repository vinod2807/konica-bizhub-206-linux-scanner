CC ?= cc
CFLAGS ?= -O2 -g -Wall -Wextra -fPIC
CPPFLAGS += -I/usr/include/sane
LDFLAGS += -shared -Wl,-soname,libsane-ar206.so.1
LIBS = -lsane -lusb-1.0

LIB = libsane-ar206.so.1.0.0

all: $(LIB)

$(LIB): ar206.c
	$(CC) $(CPPFLAGS) $(CFLAGS) $(LDFLAGS) -o $@ $< $(LIBS)
	ln -sf $(LIB) libsane-ar206.so.1
	ln -sf $(LIB) libsane-ar206.so

clean:
	rm -f $(LIB) libsane-ar206.so.1 libsane-ar206.so

install: $(LIB)
	install -d /usr/lib/sane
	install -m 755 $(LIB) /usr/lib/sane/$(LIB)
	ln -sf $(LIB) /usr/lib/sane/libsane-ar206.so.1
	ln -sf $(LIB) /usr/lib/sane/libsane-ar206.so
	install -m 644 ar206.conf /etc/sane.d/ar206.conf
	install -d /etc/sane.d/dll.d
	install -m 644 ar206.dll /etc/sane.d/dll.d/ar206

uninstall:
	rm -f /usr/lib/sane/$(LIB) /usr/lib/sane/libsane-ar206.so.1 /usr/lib/sane/libsane-ar206.so
	rm -f /etc/sane.d/ar206.conf /etc/sane.d/dll.d/ar206

.PHONY: all clean install uninstall
