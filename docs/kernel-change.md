# HTree 검색 정책 실험용 커널 변경

Linux v5.4.214의 `fs/ext4/namei.c`에서 HTree 내부 노드의 hash entry를 고르는 방법만 바꾼다. 원본 이진 검색, 선형 검색, 작은 노드에서만 선형 검색하는 혼합 정책을 같은 부팅에서 비교한다. 효과가 있다는 결론을 전제하지 않는다.

패치: `patches/0001-ext4-htree-search-experiment.patch`

## 원본과 변경 범위

- 원본: <https://github.com/gregkh/linux/blob/v5.4.214/fs/ext4/namei.c>
- 원본 파일 SHA-256: `85db4ac759bf2929ea3291494dab6e87a2369d42d8d75faae47e88426ca016fe`
- 원본 Git blob: `aaf1ed8ba87c18864c3c4f92ca4e8e39f5b7cee5`
- 변경 파일은 `fs/ext4/namei.c` 하나다. 디렉터리 저장 형식, 이름 hash 함수, leaf의 이름 비교, 충돌 시 다음 leaf로 진행하는 규칙은 유지한다.
- 정책은 `dx_probe()`를 호출하는 모든 작업에 적용된다. 계측의 프로세스 필터와 달리 검색 정책 자체는 전역이다. 파일 생성·삭제·열거도 원래 호출 경로에서 같은 entry를 선택해야 한다.
- 노드의 `count`는 sentinel을 포함한 HTree index entry 수다. 디렉터리의 파일 수나 leaf 안의 파일명 항목 수와 다르다.

## 검색 결과의 의미

entry 0은 count/limit와 첫 자식 블록을 담는 sentinel이다. entry 0의 hash 필드는 비교하지 않는다. 유효한 hash entry는 1부터 `count - 1`까지다.

두 검색 모두 **요청 hash 이하인 가장 오른쪽 entry**를 선택하고, 그런 entry가 없으면 entry 0을 선택한다. 같은 hash가 여러 번 나타나면 마지막 entry를 고른다. 비교는 원본과 같은 부호 없는 32비트 hash 값으로 하며 collision continuation 비트를 새로 마스킹하지 않는다.

- `count == 1`: 비교 없이 entry 0을 반환한다.
- 이진 검색: 원본의 `p`, `q`, `m` 비교·진행 순서를 별도 inline 함수로 옮겼다.
- 선형 검색: entry 1부터 검사하고, 처음으로 요청보다 큰 hash를 만나면 바로 이전 entry를 반환한다.
- 혼합 검색: `count <= htree_linear_limit`일 때 선형, 그 밖에는 이진 검색한다.

## 실행 중 제어

매개변수 위치는 `/sys/module/ext4/parameters/`다. 한 실험이 끝난 뒤에만 정책을 바꾼다.

| 이름 | 기본값 | 의미 |
|---|---:|---|
| `htree_search` | 0 | 0: 원본 이진 검색, 1: 선형 검색, 2: 혼합 검색. 0~2 이외 값은 거부 |
| `htree_linear_limit` | 8 | 혼합 정책의 count 경계. 0이면 모든 유효 노드에서 이진 검색 |
| `htree_profile` | N | 원인 확인용 계측. 시간 비교 때는 반드시 N |
| `htree_stats` | 읽기 전용 | 누적 계수와 count 분포를 `이름=값`으로 출력 |
| `htree_reset` | 쓰기 전용 | 벤치마크 종료 및 계측 해제 뒤 1을 써서 초기화. 계측이 켜져 있으면 `EBUSY` |

예를 들어 혼합 정책의 원인을 확인할 때는 아래 순서를 사용한다. 이 실행의 시간은 성능 비교에 쓰지 않는다.

```sh
P=/sys/module/ext4/parameters
echo 0 | sudo tee "$P/htree_profile"
echo 1 | sudo tee "$P/htree_reset"
echo 2 | sudo tee "$P/htree_search"
echo 8 | sudo tee "$P/htree_linear_limit"
echo 1 | sudo tee "$P/htree_profile"
# 여기에서 lookup_bench를 실행하고 종료를 기다린다.
echo 0 | sudo tee "$P/htree_profile"
cat "$P/htree_stats"
```

## 계측의 범위와 한계

계측은 `current->comm`이 정확히 `lookup_bench`인 태스크만 집계한다. 벤치마크는 해당 이름을 설정해야 한다. 같은 이름의 태스크를 동시에 실행하지 않는다. 파일시스템이나 디렉터리 단위 필터는 없다.

| 계수 | 의미 |
|---|---|
| `find` | `__ext4_find_entry()` 진입 수. VFS dcache에서 끝난 조회는 포함하지 않음 |
| `dx_lookup` | `ext4_dx_find_entry()` 진입 수 |
| `probe` | `dx_probe()` 진입 수. 일반적으로 한 조회에서 여러 내부 노드를 방문할 수 있음 |
| `nodes`, `count_sum` | 방문한 유효 내부 노드 수와 count 합 |
| `binary_nodes`, `linear_nodes` | 각 검색 방법을 사용한 노드 수 |
| `comparisons` | 같은 노드를 계측용으로 다시 검색하여 센 C 코드 수준의 hash 비교 수. CPU 명령어나 하드웨어 branch 계수가 아님 |
| `leaf_blocks` | `ext4_search_dir()` 호출 수. 고유 블록 수나 디스크 읽기 횟수가 아니며 inline 검색도 이 함수를 쓰면 포함됨 |
| `leaf_entries` | 정상 검색이 방문한 dirent 수를 재순회해 센 값. 삭제된 항목 등도 원래 루프가 방문하면 포함 |
| `leaf_errors` | `ext4_search_dir()`의 오류 반환 수. 오류 검색의 dirent 수는 `leaf_entries`에 더하지 않음 |
| `mismatches` | 실제 선택한 내부 entry가 원본 이진 검색 결과와 달랐던 횟수. 정상 실험에서는 0이어야 함 |

count 분포는 1, 2, 3~4, 5~8, 9~16, 17~32, 33~64, 65~128, 129~256, 257~512, 513 이상으로 집계한다. 평균 count만으로 작은 노드의 빈도를 판단하지 않는다.

계수는 `atomic64_t`로 누적하여 다른 CPU에서 실행돼도 갱신을 잃지 않게 했다. 여러 계수를 읽는 전체 과정이나 초기화 전체가 하나의 원자적 스냅샷인 것은 아니다. **벤치마크 종료 → 계측 해제 → 결과 읽기/초기화** 순서를 지킨다.

시간 측정에서는 반복문 안에 계측용 카운터나 분기를 넣지 않는다. 계측을 켠 실행만 노드 검색과 dirent 순회를 별도로 재실행한다. 따라서 계측 실행은 캐시 상태와 CPU 비용을 바꾸며, 그 시간은 비교 자료가 될 수 없다.

계측을 꺼도 정책 선택과 함수 진입부의 계측 gate는 남는다. 같은 커널의 이진/선형/혼합 비교는 이 공통 변경을 포함한 비교다. 수정하지 않은 B0와 완전히 같다고 가정하지 않고 별도 원본 커널 비교로 영향을 확인해야 한다.

## 현재 확인한 것

- 공식 v5.4.214 파일에 `git apply --check` 통과, 적용 뒤 생성한 수정 파일과 바이트 단위 일치 확인.
- 수정 파일의 실제 두 검색 함수 본문을 추출하여 userspace 검증: 527,360개 질의에서 독립적인 마지막 유효 entry 계산과 일치. count 1~512 및 1,024·4,096·8,192, 중복 hash, 전부 0, 전부 `UINT32_MAX`, 경계 질의를 포함. AddressSanitizer·UndefinedBehaviorSanitizer 오류 없음.
- 위 검증은 검색 함수의 결과와 메모리 경계를 검사한다. 커널 전체의 빌드·부팅·동시성·쓰기 정확성을 대신하지 않는다. 실제 커널 실행 결과는 결과 문서에 별도로 기록한다.
