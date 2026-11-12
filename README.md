# ucg-assist

CISO Assistant Community를 컴플라이언스 관리의 중심(Core)으로 두고, 기준 간 매핑표(Mapping Table)를 OSCAL로 관리하기 위한 저장소입니다.

매핑의 원본은 [kr-compliance-ai](https://github.com/3iuy-prog/kr-compliance-ai)의 `data/crossmap.json`입니다. 이 파일은 ISMS-P 인증기준 항목을 안전성 확보조치 기준(고시)과 법령 조문에 연결합니다. 이 저장소의 변환 코드는 crossmap.json을 OSCAL로 바꾸고, OSCAL을 다시 CISO Assistant 라이브러리로 바꿉니다. 변환 단계에서는 AI가 OSCAL을 만들거나 고치지 않습니다.

```
crossmap.json ──(tools/crossmap_to_oscal.py)──▶ OSCAL catalog·mapping-collection
                                               │  (tools/validate_oscal.py: NIST OSCAL 1.2.3 스키마 검사)
                                               ▼
                      (tools/oscal_to_ciso.py)──▶ CISO Assistant 라이브러리 YAML ──▶ CISO Assistant
```

## CISO Assistant 실행

[CISO Assistant Community](https://github.com/intuitem/ciso-assistant-community) v4.2.3의 공식 compose 파일을 바탕으로 `compose.yaml`을 만들었습니다. 공식 파일과 다른 점은 다음과 같습니다.

- 이미지를 `latest` 대신 v4.2.3 태그와 digest로 고정했습니다.
- `DJANGO_DEBUG`를 `False`로 두고, `DJANGO_SECRET_KEY`는 `scripts/setup.sh`가 만든 로컬 `.env`에서 읽습니다.
- 다른 스택과 컨테이너 이름이 겹치지 않도록 `container_name`을 지웠습니다.
- qdrant 포트는 호스트에 열지 않습니다. 화면은 `https://localhost:8443`(caddy, 127.0.0.1)에서만 열립니다.
- MCP 서버는 선택 사항이고, 읽기 전용으로 둡니다(`docker compose --profile mcp up -d`).

이 구성은 Community 이미지만으로 동작합니다. CISO Assistant 저장소의 `enterprise` 디렉터리는 별도 상용 라이선스 영역이라 사용하지 않습니다.

```sh
sh scripts/setup.sh          # .env 에 DJANGO_SECRET_KEY 생성(이미 있으면 그대로 둠)
docker compose up -d
docker compose exec backend python manage.py createsuperuser
```

데이터는 `./db`(SQLite)에 쌓입니다. 처음부터 다시 시작하려면 `docker compose down`으로 멈춘 뒤 `db` 폴더를 지웁니다.

## 매핑 변환

```sh
python3 tools/crossmap_to_oscal.py <kr-compliance-ai>/data/crossmap.json build/oscal
python3 tools/validate_oscal.py build/oscal
python3 tools/oscal_to_ciso.py build/oscal build/ciso
```

`build/ciso/*.yaml`을 CISO Assistant 화면의 라이브러리 메뉴에서 올리거나 `POST /api/stored-libraries/upload/`로 올립니다. framework 라이브러리를 먼저 올리고 매핑 라이브러리를 나중에 올립니다.

### 변환 규칙

- ISMS-P 항목, 고시, 법령마다 OSCAL catalog를 하나씩 만듭니다. 법령은 법령별로 catalog를 나눠 조문 ID(`art-29` 등)가 겹치지 않게 합니다.
- 매핑의 관계 종류는 crossmap.json에 사람이 적은 값만 씁니다. 각 연결에 `relationship`, `matching_rationale`, `relationship_basis`(판단 근거 문장)가 있어야 OSCAL 매핑이 됩니다. 관계가 비어 있는 연결은 OSCAL에 넣지 않고 `report.json`의 `unresolved`에 남깁니다.
- crossmap.json의 `verified` 값은 OSCAL에 `crossmap-verified` 속성으로 옮깁니다. 이 값은 원문 대조 상태이며, 매핑 관계가 타당한지와는 별개입니다.
- OSCAL 관계 값은 아래 표대로 CISO Assistant 관계 값으로 바꿉니다. 두 쪽 모두 source를 target과 비교한 관계라서 방향은 같습니다.

| OSCAL | CISO Assistant |
| --- | --- |
| `equal-to` | `equal` |
| `subset-of` | `subset` |
| `superset-of` | `superset` |
| `intersects-with` | `intersect` |
| `equivalent-to`, `no-relationship` | 옮기지 않음(`report.json`의 `excluded`에 남김) |

- `matching_rationale`(syntactic·semantic·functional)은 CISO Assistant 매핑의 `rationale`로, 판단 근거 문장은 `annotation`으로 옮깁니다.
- UUID는 uuid5로, 날짜는 crossmap.json의 `_meta.updated`로 정합니다. 같은 입력을 다시 변환하면 같은 파일이 나옵니다.
- 라이브러리 버전은 `YYYYMMDDNN`입니다. 앞 여덟 자리는 `_meta.updated`이고, 끝 두 자리는 `--revision`(기본 0)입니다. CISO Assistant는 버전이 커질 때만 라이브러리를 갱신하므로, 같은 날 crossmap.json을 고쳐 다시 올릴 때는 `--revision`을 올립니다.
- 두 변환기는 출력 폴더를 비우고 다시 씁니다. 그래서 지난번 실행에서 만든 매핑 파일이 남아 다시 올라가지 않습니다. 이 도구가 만들지 않은 폴더(표식 파일 `.ucg-assist-output`이 없는 폴더)에 파일이 있으면 지우지 않고 실행을 멈춥니다.
- 변환 결과는 `build/`에 생기며, `build/`는 저장소에서 추적하지 않습니다.

## 시험

```sh
python3 -m unittest discover -s tests -v
```

시험에는 합성 데이터(`tests/fixtures/crossmap-synthetic.json`)만 씁니다. 시험 항목은 출력의 재현성, 스키마 검사, 관계 미정 연결 제외, 관계 값 대응과 방향, 지원하지 않는 관계의 보고, 미검증 표시, 잘못된 입력 거부, 같은 폴더 재변환 시 이전 생성물 제거, revision에 따른 버전 증가입니다.

## 알려진 한계

- crossmap.json에는 법령의 시행일·판 정보가 없어서 `source-version`을 `미기재`로 둡니다.
- CISO Assistant 매핑 라이브러리에는 정방향(ISMS-P → 고시·법령)만 넣습니다. 역방향 매핑은 만들지 않습니다.
- v4.2.3에서는 같은 URN의 매핑 라이브러리를 버전을 올려 다시 올리면 저장된 라이브러리 내용이 바로 바뀝니다. 다만 화면의 로드된 라이브러리 버전은 이전 값으로 남습니다. framework 라이브러리를 갱신하는 경로와 실패했을 때 복구하는 방법은 아직 시험하지 않았습니다.

## 스키마 검사 구현 메모

- NIST 스키마의 정규식에 있는 `\p{L}`·`\p{N}`은 파이썬 `re`가 지원하지 않습니다. 그래서 검사 전에 `[^\W\d_]`·`\d`로 바꿉니다.
- URI 형식(`uri`, `uri-reference`) 검사는 `jsonschema`의 형식 검사 의존성이 설치되어 있을 때만 동작합니다.
- OSCAL 관계 값의 허용 목록은 JSON 스키마에 없습니다. NIST OSCAL 1.2.3 문서를 보고 코드에 적어 두었습니다.

## 라이선스

AGPL-3.0. 이 저장소에는 CISO Assistant(AGPL-3.0)의 코드가 들어 있지 않고, 공식 이미지를 실행하는 설정과 변환 도구만 들어 있습니다.
