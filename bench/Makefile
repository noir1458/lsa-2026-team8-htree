CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra -Werror

.PHONY: all clean
all: lookup_bench dx_search_bench

lookup_bench: lookup_bench.c
	$(CC) $(CFLAGS) $< -o $@

dx_search_bench: dx_search_bench.c
	$(CC) $(CFLAGS) $< -o $@

clean:
	rm -f lookup_bench dx_search_bench
