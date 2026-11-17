#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <inttypes.h>

/* Entry zero is a sentinel; hashes are nondecreasing from entry one. */
struct entry { uint32_t hash, block; };
static uint64_t rng=0x943a587512caf321ULL;
static volatile uint64_t sink;
static uint32_t random32(void) { rng^=rng<<13; rng^=rng>>7; rng^=rng<<17; return (uint32_t)(rng>>16); }
__attribute__((noinline)) static unsigned binary(const struct entry *e,unsigned n,uint32_t h) {
    int lo=1,hi=(int)n-1;
    while(lo<=hi) { int m=lo+(hi-lo)/2; if(e[m].hash>h) hi=m-1; else lo=m+1; }
    return (unsigned)(lo-1);
}
__attribute__((noinline)) static unsigned linear(const struct entry *e,unsigned n,uint32_t h) {
    unsigned i=1; while(i<n && e[i].hash<=h) ++i; return i-1;
}
static uint64_t ns(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t);return (uint64_t)t.tv_sec*1000000000ULL+t.tv_nsec; }
static void fill(struct entry *e,unsigned n) {
    e[0]=(struct entry){0xdeadbeef,0};
    for(unsigned i=1;i<n;i++) e[i]=(struct entry){(uint32_t)(((uint64_t)i*UINT32_MAX)/n),i};
}
static void check(void) {
    struct entry e[513]; uint64_t checks=0;
    for(unsigned n=1;n<=512;n++) {
        fill(e,n);
        for(unsigned pattern=0;pattern<3;pattern++) {
            if(pattern==1) for(unsigned i=1;i<n;i++) e[i].hash=(i/4)*8;
            if(pattern==2) for(unsigned i=1;i<n;i++) e[i].hash=UINT32_MAX;
            for(unsigned i=0;i<1000+n*3;i++) {
                uint32_t h=i<3*n ? (i%3==0 ? e[i/3].hash : i%3==1 ? e[i/3].hash-1 : e[i/3].hash+1) : random32();
                unsigned a=binary(e,n,h),b=linear(e,n,h);
                if(a!=b || (a && e[a].hash>h) || (a+1<n && e[a+1].hash<=h)) {fprintf(stderr,"FAIL n=%u h=%u a=%u b=%u\n",n,h,a,b);exit(2);} checks++;
            }
        }
    }
    fprintf(stderr,"correctness_checks=%"PRIu64" passed\n",checks);
}
int main(int argc,char **argv) {
    unsigned iterations=argc>1?(unsigned)strtoul(argv[1],0,10):2000000;
    unsigned rounds=argc>2?(unsigned)strtoul(argv[2],0,10):10;
    if(!iterations||!rounds)return 2;
    check();
    struct entry e[513]; uint32_t queries[8192];
    unsigned sizes[]={1,2,4,8,16,32,64,83,128,256,436,442,507,510};
    const char *names[]={"binary","linear"};
    for(unsigned i=0;i<8192;i++)queries[i]=random32();
    puts("round,count,mode,iterations,total_ns,ns_per_search,checksum");
    for(unsigned r=0;r<rounds;r++)for(unsigned s=0;s<sizeof(sizes)/sizeof(sizes[0]);s++) {
        unsigned n=sizes[s];fill(e,n);
        for(unsigned k=0;k<2;k++) {
            unsigned mode=(k+r)%2; unsigned (*fn)(const struct entry*,unsigned,uint32_t)=mode?linear:binary;
            uint64_t sum=0;for(unsigned i=0;i<8192;i++)sum+=fn(e,n,queries[i]);sink=sum;
            uint64_t t=ns();sum=0;
            for(unsigned i=0;i<iterations;i++)sum+=fn(e,n,queries[i&8191]);
            uint64_t elapsed=ns()-t;sink=sum;
            printf("%u,%u,%s,%u,%"PRIu64",%.6f,%"PRIu64"\n",r,n,names[mode],iterations,elapsed,(double)elapsed/iterations,sum);
        }
    }
    return 0;
}
