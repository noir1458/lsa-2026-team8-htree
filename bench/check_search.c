#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <assert.h>
typedef uint32_t u32;
struct dx_entry { u32 hash, block; };
static u32 dx_get_hash(struct dx_entry *e) { return e->hash; }
/* Extracted at test time from the actual kernel patch. */
#include "htree_search_helpers.h"

static uint64_t rng = 0x582a27b752c37194ULL;
static uint32_t rnd(void) { rng ^= rng << 13; rng ^= rng >> 7; rng ^= rng << 17; return (uint32_t)rng; }
static int cmp(const void *a,const void *b) { u32 x=((const struct dx_entry *)a)->hash,y=((const struct dx_entry *)b)->hash; return (x>y)-(x<y); }
static unsigned long checks;
static void run(unsigned n) {
    struct dx_entry *e=malloc(sizeof(*e)*n);
    assert(e);
    for(unsigned pat=0;pat<4;pat++) {
        e[0].hash=0xffffffffU;
        for(unsigned i=1;i<n;i++) { e[i].block=i; e[i].hash=pat==0 ? rnd() : pat==1 ? (i/4)*8 : pat==2 ? 0xffffffffU : 0; }
        qsort(e+1,n-1,sizeof(*e),cmp);
        for(unsigned q=0;q<256;q++) {
            unsigned at=q%n;
            u32 h=q<3 ? (q==0 ? 0 : q==1 ? 0xffffffffU : 1) : q%3==0 ? e[at].hash : q%3==1 ? e[at].hash-1 : rnd();
            unsigned expected=0;
            for(unsigned i=1;i<n;i++) if(e[i].hash<=h)expected=i;
            assert(htree_binary_search(e,n,h)==e+expected);
            assert(htree_linear_search(e,n,h)==e+expected);
            checks++;
        }
    }
    free(e);
}
int main(void) { for(unsigned n=1;n<=512;n++)run(n); run(1024);run(4096);run(8192);printf("exact_kernel_helper_checks=%lu passed\n",checks); }
