<!--
 * @Author: caiyinghan 455202662@qq.com
 * @Date: 2025-08-24 16:37:50
 * @LastEditors: caiyinghan 455202662@qq.com
 * @LastEditTime: 2025-08-24 20:27:28
 * @FilePath: \transaction_push\tests\README.md
 * @Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
-->
# 测试目录

这个目录包含项目的所有测试文件。

## 测试文件说明

- `test_config.py` - 配置加载和验证测试
- `test_services.py` - 服务功能测试

## 运行测试

### 使用pytest运行所有测试
```bash
pytest tests/
```

### 运行单个测试文件
```bash
python tests/test_config.py
python tests/test_services.py
```

### 使用pytest运行特定测试
```bash
pytest tests/test_config.py::test_config_loading
pytest tests/test_services.py::test_okx_service_connection
```

## 测试规范

1. 所有测试文件以 `test_` 开头
2. 测试函数以 `test_` 开头
3. 异步测试使用 `@pytest.mark.asyncio` 装饰器
4. 使用中文注释和文档字符串
5. 测试应该独立运行，不依赖外部状态

## 添加新测试

在添加新功能时，请在相应的测试文件中添加测试用例，或创建新的测试文件。