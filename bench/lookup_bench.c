#define _POSIX_C_SOURCE 200809L
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <getopt.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/utsname.h>
#include <time.h>
#include <unistd.h>

struct query { char *name; int exists; };
static uint64_t rng_state;
static uint64_t random64(void) {
    uint64_t z = (rng_state += UINT64_C(0x9e3779b97f4a7c15));
    z = (z ^ (z >> 30)) * UINT64_C(0xbf58476d1ce4e5b9);
    z = (z ^ (z >> 27)) * UINT64_C(0x94d049bb133111eb);
    return z ^ (z >> 31);
}
static void die(const char *what) { perror(what); exit(2); }
static void fail(const char *what) { fprintf(stderr, "%s\n", what); exit(2); }
static uint64_t now_ns(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t)) die("clock_gettime");
    return (uint64_t)t.tv_sec * UINT64_C(1000000000) + (uint64_t)t.tv_nsec;
}
static uint64_t number(const char *s) {
    char *end; unsigned long long n;
    if (!s[0] || s[0] == '-') fail("expected nonnegative integer");
    errno = 0; n = strtoull(s, &end, 10);
    if (errno || *end) fail("invalid integer");
    return (uint64_t)n;
}
static void *allocate(size_t n, size_t size) {
    if (size && n > SIZE_MAX / size) fail("allocation overflow");
    void *p = calloc(n, size);
    if (!p) die("calloc");
    return p;
}
static void validate_name(const char *s) {
    if (!*s || strlen(s) > 255 || strchr(s, '/') || strchr(s, '\n') ||
        strchr(s, '\r') || !strcmp(s,".") || !strcmp(s,".."))
        fail("names must be single directory components of 1..255 bytes");
}
static void append(struct query **qs, size_t *n, size_t *cap,
                   const char *name, int exists) {
    validate_name(name);
    if (*n == *cap) {
        if (*cap > SIZE_MAX / 2 / sizeof(**qs)) fail("too many queries");
        *cap = *cap ? *cap * 2 : 128;
        void *p = realloc(*qs, *cap * sizeof(**qs));
        if (!p) die("realloc");
        *qs = p;
    }
    (*qs)[*n].name = strdup(name);
    if (!(*qs)[*n].name) die("strdup");
    (*qs)[(*n)++].exists = exists;
}
static int compare_u64(const void *a, const void *b) {
    uint64_t x = *(const uint64_t *)a, y = *(const uint64_t *)b;
    return (x > y) - (x < y);
}
static uint64_t percentile(const uint64_t *a, size_t n, unsigned p) {
    /* nearest-rank percentile, p=1..100 */
    size_t idx = (n / 100) * p + ((n % 100) * p + 99) / 100;
    return a[idx ? idx - 1 : 0];
}
static void byte_write(int fd) {
    char c = 'R'; ssize_t rc;
    do { rc = write(fd, &c, 1); } while (rc < 0 && errno == EINTR);
    if (rc != 1) die("ready fd write");
    close(fd);
}
static void byte_read(int fd) {
    char c; ssize_t rc;
    do { rc = read(fd, &c, 1); } while (rc < 0 && errno == EINTR);
    if (rc != 1) fail("start fd closed without start byte");
    close(fd);
}
static void warm_directory(int fd) {
    int copy = dup(fd); if (copy < 0) die("dup directory");
    DIR *d = fdopendir(copy); if (!d) die("fdopendir");
    errno = 0;
    while (readdir(d)) { }
    if (errno) die("readdir");
    if (closedir(d)) die("closedir");
}
static size_t run_pass(int fd, const struct query *q, size_t n,
                       uint64_t *latency, uint64_t *digest) {
    size_t errors = 0;
    for (size_t i = 0; i < n; i++) {
        struct stat st;
        uint64_t start = latency ? now_ns() : 0;
        int rc = fstatat(fd, q[i].name, &st, AT_SYMLINK_NOFOLLOW);
        int saved_errno = errno;
        if (latency) latency[i] = now_ns() - start;
        int ok = q[i].exists ? (rc == 0 && S_ISREG(st.st_mode))
                            : (rc == -1 && saved_errno == ENOENT);
        if (!ok) {
            if (errors < 5)
                fprintf(stderr,"unexpected result: query=%zu name=%s expected=%s rc=%d errno=%d\n",
                        i, q[i].name, q[i].exists ? "regular-file" : "ENOENT", rc, saved_errno);
            errors++;
        }
        /* Hash the semantic result, not inode numbers (different filesystems). */
        uint64_t v = ok ? (q[i].exists ? 1 : 2) : 3;
        *digest = (*digest ^ (v + (uint64_t)i * 17)) * UINT64_C(1099511628211);
    }
    return errors;
}
static void usage(const char *prog) {
    fprintf(stderr,
      "Usage: %s --dir DIR [--files N --positive N --negative N | --names FILE]\n"
      "  Generated hits: file_00000000..file_(N-1); misses: absent_SEED_INDEX\n"
      "  --positive defaults to --files; --negative defaults to --files\n"
      "  --names FILE: lines '1 filename' (regular file) or '0 filename' (ENOENT)\n"
      "  --seed N       deterministic shuffle/name seed (default 1)\n"
      "  --repeat N     measured passes (default 1; later passes reuse names/cache)\n"
      "  --warmup N     untimed passes over the same names (default 0)\n"
      "  --warm-dir     enumerate names before timing; does not stat child files\n"
      "  --trial N --label WORD --latencies FILE --no-header\n"
      "  --ready-fd N --start-fd N --done-fd N --release-fd N\n"
      "                 pipe handshakes outside measurement for kernel counters\n"
      "No cache dropping or filesystem modification is performed by this program.\n",prog);
    exit(2);
}
int main(int argc, char **argv) {
    const char *dir = NULL, *names = NULL, *label = "lookup", *latpath = NULL;
    size_t files=0, positive=SIZE_MAX, negative=SIZE_MAX, repeats=1, warmups=0;
    uint64_t seed=1, trial=0;
    int warmdir=0, header=1, ready=-1, startfd=-1, done=-1, release=-1;
    enum { D=1000,F,P,N,Q,S,R,W,WD,T,L,LAT,NH,READY,START,DONE,RELEASE };
    const struct option opts[] = {
      {"dir",1,0,D},{"files",1,0,F},{"positive",1,0,P},{"negative",1,0,N},
      {"names",1,0,Q},{"seed",1,0,S},{"repeat",1,0,R},{"warmup",1,0,W},
      {"warm-dir",0,0,WD},{"trial",1,0,T},{"label",1,0,L},
      {"latencies",1,0,LAT},{"no-header",0,0,NH},{"ready-fd",1,0,READY},
      {"start-fd",1,0,START},{"done-fd",1,0,DONE},{"release-fd",1,0,RELEASE},
      {"help",0,0,'h'},{0,0,0,0}
    };
    int c;
    while ((c=getopt_long(argc,argv,"h",opts,NULL)) != -1) switch(c) {
      case D:dir=optarg;break; case F:files=(size_t)number(optarg);break;
      case P:positive=(size_t)number(optarg);break; case N:negative=(size_t)number(optarg);break;
      case Q:names=optarg;break; case S:seed=number(optarg);break;
      case R:repeats=(size_t)number(optarg);break; case W:warmups=(size_t)number(optarg);break;
      case WD:warmdir=1;break; case T:trial=number(optarg);break; case L:label=optarg;break;
      case LAT:latpath=optarg;break; case NH:header=0;break;
      case READY:ready=(int)number(optarg);break; case START:startfd=(int)number(optarg);break;
      case DONE:done=(int)number(optarg);break; case RELEASE:release=(int)number(optarg);break;
      default:usage(argv[0]);
    }
    if (!dir || optind!=argc || !repeats || strpbrk(label,",\r\n")) usage(argv[0]);
    if ((ready>=0)!=(startfd>=0) || (done>=0)!=(release>=0))
        fail("ready/start and done/release fds must be supplied as pairs");
    struct query *q=NULL; size_t n=0, cap=0;
    rng_state=seed;
    if (names) {
        FILE *f=fopen(names,"r"); if(!f)die("names file");
        char *line=NULL;size_t len=0;ssize_t got;
        while((got=getline(&line,&len,f))>=0) {
            while(got && (line[got-1]=='\n'||line[got-1]=='\r')) line[--got]=0;
            if (!got || line[0]=='#') continue;
            if ((line[0]!='0'&&line[0]!='1') || line[1]!=' ')
                fail("names file: expected '0 name' or '1 name'");
            append(&q,&n,&cap,line+2,line[0]=='1');
        }
        if(ferror(f))die("names read");
        free(line);
        fclose(f);
    } else {
        if(!files)fail("--files must be positive without --names");
        if(positive==SIZE_MAX)positive=files;
        if(negative==SIZE_MAX)negative=files;
        if(positive>files)fail("--positive cannot exceed --files (hits remain unique per pass)");
        size_t *ids=allocate(files,sizeof(*ids));
        for(size_t i=0;i<files;i++)ids[i]=i;
        for(size_t i=files;i>1;i--){size_t j=random64()%i,tmp=ids[i-1];ids[i-1]=ids[j];ids[j]=tmp;}
        for(size_t i=0;i<positive;i++) {
            char name[128];snprintf(name,sizeof name,"file_%08zu",ids[i]);
            append(&q,&n,&cap,name,1);
        }
        free(ids);
        for(size_t i=0;i<negative;i++) {
            char name[128];snprintf(name,sizeof name,"absent_%016" PRIx64 "_%08zu",seed,i);
            append(&q,&n,&cap,name,0);
        }
    }
    if(!n)fail("empty query set");
    rng_state=seed;
    for(size_t i=n;i>1;i--) { size_t j=random64()%i;struct query tmp=q[i-1];q[i-1]=q[j];q[j]=tmp; }
    positive=negative=0;
    for(size_t i=0;i<n;i++) if(q[i].exists)positive++;else negative++;
    uint64_t *lat=allocate(n,sizeof(*lat)), *sorted=allocate(n,sizeof(*sorted));
    if(repeats>SIZE_MAX/n)fail("too many samples");
    uint64_t *alllat=allocate(repeats*n,sizeof(*alllat));
    struct result {uint64_t elapsed,digest;size_t errors;} *results=allocate(repeats,sizeof(*results));
    int fd=open(dir,O_RDONLY|O_DIRECTORY);if(fd<0)die("open directory");
    if(warmdir)warm_directory(fd);
    for(size_t w=0;w<warmups;w++) {uint64_t digest=0;if(run_pass(fd,q,n,NULL,&digest))fail("warmup correctness failure");}
    /* Touch allocated buffers and timing code before the external reset hook. */
    for(size_t i=0;i<n;i++){((volatile uint64_t *)lat)[i]=0;((volatile uint64_t *)sorted)[i]=0;}
    for(size_t i=0;i<repeats*n;i++)((volatile uint64_t *)alllat)[i]=0;
    (void)now_ns();
    if(ready>=0){byte_write(ready);byte_read(startfd);}
    size_t errors=0;
    for(size_t r=0;r<repeats;r++) {
        uint64_t digest=UINT64_C(14695981039346656037), begin=now_ns();
        size_t e=run_pass(fd,q,n,lat,&digest);
        results[r]=(struct result){now_ns()-begin,digest,e};errors+=e;
        memcpy(alllat+r*n,lat,n*sizeof(*lat));
    }
    if(done>=0){byte_write(done);byte_read(release);}
    struct utsname un;if(uname(&un))die("uname");
    if(header)puts("label,kernel,trial,pass,seed,queries,positive,negative,warmups,warm_dir,elapsed_ns,mean_ns,p50_ns,p95_ns,p99_ns,min_ns,max_ns,errors,digest");
    FILE *lf=NULL;
    if(latpath){lf=fopen(latpath,"w");if(!lf)die("latencies file");fputs("trial,pass,index,expected_exists,latency_ns,name\n",lf);}
    for(size_t r=0;r<repeats;r++) {
        memcpy(sorted,alllat+r*n,n*sizeof(*sorted));qsort(sorted,n,sizeof(*sorted),compare_u64);
        long double sum=0;for(size_t i=0;i<n;i++)sum+=alllat[r*n+i];
        printf("%s,%s,%" PRIu64 ",%zu,%" PRIu64 ",%zu,%zu,%zu,%zu,%d,%" PRIu64 ",%.3Lf,%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%zu,%016" PRIx64 "\n",
          label,un.release,trial,r,seed,n,positive,negative,warmups,warmdir,results[r].elapsed,sum/n,
          percentile(sorted,n,50),percentile(sorted,n,95),percentile(sorted,n,99),sorted[0],sorted[n-1],results[r].errors,results[r].digest);
        if(lf)for(size_t i=0;i<n;i++) {
            fprintf(lf,"%" PRIu64 ",%zu,%zu,%d,%" PRIu64 ",\"",trial,r,i,q[i].exists,alllat[r*n+i]);
            for(const char *p=q[i].name;*p;p++){if(*p=='\"')fputc('\"',lf);fputc(*p,lf);}fputs("\"\n",lf);
        }
    }
    if(lf&&fclose(lf))die("latencies close");
    close(fd);for(size_t i=0;i<n;i++)free(q[i].name);
    free(q);free(lat);free(sorted);free(alllat);free(results);
    return errors?1:0;
}
