# 贡献指南 (Contributing Guide)

感谢您对 Smart Clipboard Manager 项目的关注与支持！无论是修复 Bug、完善文档、改进算法还是提出新想法，我们都非常欢迎。

## 开发工作流 (Development Workflow)

1. **Fork 本仓库** 到您个人的 GitHub 空间。
2. **克隆您的 Fork** 并创建特性分支：
   ```bash
   git clone https://github.com/YOUR_USERNAME/smart-clipboard.git
   cd smart-clipboard
   git checkout -b feature/your-feature-name
   ```
3. **配置开发环境**：
   ```powershell
   pip install -r requirements.txt
   ```
4. **进行开发与自测**：
   - 保证代码符合 PEP 8 规范，避免散落硬编码魔法常数；
   - 涉及数据结构或平台调用的修改，必须补充或同步更新 `tests/` 目录下的自动化单元测试；
   - 运行测试套件：
     ```powershell
     python -m unittest discover -s tests -p "test_*.py" -v
     ```
5. **提交代码 (Git Commit)**：
   提交信息推荐遵循 [Conventional Commits](https://www.conventionalcommits.org/) 规范：
   - `feat: 增加新功能`
   - `fix: 修复问题`
   - `docs: 文档变更`
   - `test: 增加或修改测试`
   - `refactor: 重构代码`
6. **发起 Pull Request (PR)**：
   在 GitHub 上向本仓库的 `main` 分支提交 PR，清晰描述改动的动机与验证方案。
