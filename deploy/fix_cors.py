"""
Layer 3/5/6 Function URL CORS 수정 스크립트
------------------------------------------
문제: 배포 시 Function URL이 이미 존재하면 CORS 설정을 건너뛰어서
      orchestrator 테스트 페이지에서 cross-origin 호출이 실패함.

수정: update_function_url_config로 CORS를 강제 적용.

사용법 (SageMaker 또는 AWS CLI 가능한 환경):
  python fix_cors.py
"""
import boto3

REGION = 'ap-northeast-2'
lam = boto3.client('lambda', region_name=REGION)

# CORS가 필요한 Lambda 함수들
FUNCTIONS = [
    'layer3-clinical-logic',
    'layer5-rag',
    'layer6-bedrock-report',
    # Layer 1, 2는 이미 정상 작동
]

CORS_CONFIG = {
    'AllowOrigins': ['*'],
    'AllowMethods': ['GET', 'POST'],
    'AllowHeaders': ['Content-Type'],
}

def fix_cors():
    for func_name in FUNCTIONS:
        print(f'\n[{func_name}]')
        try:
            # 현재 설정 확인
            resp = lam.get_function_url_config(FunctionName=func_name)
            current_cors = resp.get('Cors', {})
            url = resp['FunctionUrl']
            print(f'  URL: {url}')
            print(f'  현재 CORS: {current_cors}')

            # CORS 업데이트
            lam.update_function_url_config(
                FunctionName=func_name,
                Cors=CORS_CONFIG,
            )
            print(f'  CORS 업데이트 완료!')

            # 확인
            resp2 = lam.get_function_url_config(FunctionName=func_name)
            print(f'  새 CORS: {resp2.get("Cors", {})}')

        except lam.exceptions.ResourceNotFoundException:
            print(f'  Function URL 없음 - 새로 생성')
            try:
                resp = lam.create_function_url_config(
                    FunctionName=func_name,
                    AuthType='NONE',
                    Cors=CORS_CONFIG,
                )
                print(f'  생성 완료: {resp["FunctionUrl"]}')

                # public access 권한
                try:
                    lam.add_permission(
                        FunctionName=func_name,
                        StatementId='FunctionURLAllowPublicAccess',
                        Action='lambda:InvokeFunctionUrl',
                        Principal='*',
                        FunctionUrlAuthType='NONE',
                    )
                except lam.exceptions.ResourceConflictException:
                    pass
            except Exception as e:
                print(f'  생성 실패: {e}')

        except Exception as e:
            print(f'  오류: {e}')

    print('\n완료! 브라우저에서 다시 테스트하세요.')


if __name__ == '__main__':
    fix_cors()
