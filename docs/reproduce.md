# 재현 방법

아래 실행 명령은 실험용 Linux VM 기준이다. 커널은 Linux 5.4.214, 측정 당시 컴파일러는 GCC 9.4.0이었다. 기존 수업 소스와 데이터를 사용하지 않고 별도 소스 트리와 작업 디렉터리를 만든다.

## 커널

원본 B0는 수정하지 않은 Linux 5.4.214에 `results/config-5.4.214-b0`를 적용한 커널이다. 이번 측정에서는 이미 설치돼 있던 `5.4.214-b0`를 사용했다. 새로 만들 경우 새 원본 소스 디렉터리에서 다음을 실행한다.

```sh
cp /path/to/this-repo/results/config-5.4.214-b0 /path/to/b0-source/.config
cd /path/to/b0-source
make olddefconfig
make -j2 bzImage modules
sudo make modules_install
sudo make install
```

패치 커널은 다른 새 원본 소스 디렉터리에서 만든다.

```sh
cd /path/to/this-repo
bash scripts/build_kernel.sh /path/to/htree-source
cd /path/to/htree-source
sudo make modules_install
sudo make install
```

설치된 GRUB 항목 이름을 확인하고 `grub-reboot`으로 한 번씩 선택한다. 기존 기본 부팅 항목은 바꾸지 않는다. 실행 전 `uname -r`로 실제 커널을 확인한다. 기록한 B0/htree1 설정은 `CONFIG_LOCALVERSION` 한 줄만 다르다. 설치된 이미지·설정의 해시는 `results/installed-kernels.sha256`에 있다.

## 독립된 측정 작업 디렉터리

저장소의 `results/`에는 이미 완료한 자료가 있다. 그 위에 재측정하지 않는다. 같은 작업 디렉터리를 두 커널 부팅에서 사용한다.

```sh
cd /path/to/this-repo
make -C bench
bash scripts/check_search.sh
experiment_dir="$HOME/htree-new-run"
mkdir "$experiment_dir"
cp -R bench scripts patches "$experiment_dir/"
mkdir "$experiment_dir/results"
sudo bash "$experiment_dir/scripts/create_images.sh" "$experiment_dir"
```

`create_images.sh`는 작업 디렉터리에 새로 만드는 일반 파일 이미지 두 개만 포맷한다. 기존 이미지가 있으면 중단한다. 각각 128 MiB·4 KiB 블록의 ext4이고, 인덱스 유무와 같은 hash seed를 설정한다. 파일 이름은 `file_%08d`, 내용은 비어 있다. 디렉터리 생성 순서는 고정 seed로 섞는다. 실제 INDEX 플래그는 `flags-*.txt`, 실제 HTree 노드 크기는 `htree-structure.txt`를 참고한다. features의 dir_index와 디렉터리 inode의 INDEX 플래그는 구분한다.

파일 생성이 끝나고 이미지에 다른 쓰기가 없는 상태에서 실제 인덱스 구조를 읽는다. `debugfs`에 `-w`를 주지 않는다.

```sh
for n in 1000 10000 100000; do
  echo "directory=n$n"
  sudo debugfs -R "htree_dump /n$n" "$experiment_dir/fixtures/indexed.img" 2>/dev/null |
    awk '/Root node dump|Indirect levels|Number of entries/'
done > "$experiment_dir/results/htree-structure.txt"
```

## 원본과 패치 측정

원본 B0로 부팅한 다음:

```sh
experiment_dir="$HOME/htree-new-run"
sudo bash "$experiment_dir/scripts/mount_images.sh" "$experiment_dir"
python3 "$experiment_dir/scripts/wait_idle.py"
python3 "$experiment_dir/scripts/capture_environment.py" > "$experiment_dir/results/environment-stock.json"
sudo bash "$experiment_dir/scripts/run_suite.sh" "$experiment_dir" stock 10
```

패치 커널 `5.4.214-htree1`로 부팅한 다음:

```sh
experiment_dir="$HOME/htree-new-run"
sudo bash "$experiment_dir/scripts/run_patched_experiment.sh" "$experiment_dir"
```

이 스크립트는 변경 동작 검사, 부팅 안정화, 정책별 시간 측정, 인덱스 유무 대조, 별도 계측, 마이크로벤치마크, 이미지 분리 후 읽기 전용 fsck를 순서대로 실행한다. 종료 때 검색 정책과 임계값을 복원하고 계측을 끈다. 부팅 후 240초 이상·1분 부하 0.6 미만을 3회 연속 확인한다.

시간 비교와 계측은 다른 실행이다. `run_suite.sh`는 계측을 0으로 강제하고, `run_profile.sh`만 1로 켠다. 각 trial 전 sync와 drop_caches=2를 사용한다. `warmdir`는 이름 목록만 열거하고, `warm`은 같은 질의를 미리 한 번 실행한다. `warmdir`를 물리 디스크까지 완전히 비운 cold I/O라고 해석하지 않는다.

추가 확인은 `docs/confirmation-plan.md`에 정한 별도 부팅에서 실행했다.

```sh
experiment_dir="$HOME/htree-new-run"
sudo bash "$experiment_dir/scripts/run_confirmation.sh" "$experiment_dir"
```

기존 자료를 대체하지 않으며, `confirm-n*`에 별도로 저장한다. 모든 출력 디렉터리는 새로워야 한다. 중간 실패 후에는 완료된 단계와 로그를 확인하고 재개한다.

## 분석

저장소에 포함한 이번 원자료를 다시 집계하려면 다음을 실행한다. Python 3와 Matplotlib이 필요하다.

```sh
python3 analysis/analyze_results.py --latencies
python3 analysis/analyze_confirmation.py --latencies
python3 analysis/plot_results.py
python3 analysis/plot_confirmation.py
```

새로 수집한 결과는 별도 분석 디렉터리를 지정한다. 로컬로 복사했다면 `experiment_dir`를 그 복사본의 경로로 바꾼다.

```sh
analysis_dir="$experiment_dir/analysis"
python3 analysis/analyze_results.py --results "$experiment_dir/results" --output "$analysis_dir" --latencies
python3 analysis/analyze_confirmation.py --results "$experiment_dir/results" --output "$analysis_dir" --latencies
python3 analysis/plot_results.py --analysis "$analysis_dir" --results "$experiment_dir/results" --output "$analysis_dir"
python3 analysis/plot_confirmation.py --analysis "$analysis_dir" --output "$analysis_dir"
```

질의별 지연은 측정 후 `.latencies.csv.gz`로 압축했다. 압축 전후의 숫자는 같으며 분석기는 둘 다 읽는다. 로그·메타데이터의 접속 계정과 호스트 표시는 공유용으로 치환했다. 질의, 지연, 계수, 정책, seed 값은 바꾸지 않았다.

주 지표는 `elapsed_ns / queries`다. 개별 시스템 호출만 잰 `mean_ns`와 구분한다. 정책 변화율은 같은 round의 정책/binary 비율을 먼저 구한 뒤 중앙값을 계산한다. 서로 다른 부팅의 B0와 patched-binary는 이 방식으로 짝짓지 않는다. 큰 오차 막대는 관측한 최소~최대이며 신뢰구간이 아니다.
