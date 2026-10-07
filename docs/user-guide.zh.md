# KinoDraw 使用指南

[English](user-guide.md)

KinoDraw 在你自己的电脑上把一篇讲稿变成手绘视频：一只手画出涂鸦、便签和小图表，同时有声音朗读你的文字。本指南按步骤介绍这个应用。应用的按钮是英文的，下面用粗体写出按钮上的原文。

## 安装并打开 KinoDraw

1. 从[下载页](https://github.com/edwardaiwang-svg/kinodraw/releases/latest)下载 Windows、macOS（Apple 芯片）或 Linux 版，然后解压。
2. 打开它。第一次打开时电脑会要求你确认一次：Mac 上到“系统设置 → 隐私与安全性”点“仍要打开”（[每一步的图](https://edwardaiwang-svg.github.io/kinodraw/#first-open)）；Windows 上点“更多信息 → 仍要运行”。
3. 第一次打开时，KinoDraw 会播放一个做好的示例视频；以后会打开你最近的视频。**Watch an example** 可以再看一次示例。

如果你是用 Python 安装的，`kinodraw studio` 会打开同样的窗口，`kinodraw studio --browser` 则在浏览器里打开。

## 做第一个视频

![New video 页面和示例讲稿](media/guide/new-video.jpg)

1. 点 **New video**。
2. 粘贴讲稿，或点 **Choose file…** 打开 .md、.txt 或 .docx 文件，也可以在 **Start from an example** 下选一篇虚构的示例。
3. 看一下 **Language**、**Narrator**、**Director**、**Style** 和 **Format**。用默认设置就可以。
4. 点 **Create storyboard**。KinoDraw 会为讲稿的每一部分安排画面。
5. 检查分镜，然后点 **Make video**。3 分钟的视频大约要做 3 分钟。

每种语言的第一个视频会下载一次声音（约 190 MB，中文约 220 MB）和涂鸦搜索（约 70 MB，中文约 95 MB）。之后一切都可以离线使用。

## 写讲稿

- 用 `#` 写标题。每个 `##` 小标题是一节，会列在开头的目录卡上。
- 照你说话的方式写。数字、引语和定义会自动变成图表和便签。
- 最后一节叫“总结”（或 “Conclusion”）时，会成为结尾。
- 讲稿可以用中文、英文或西班牙文写。**Detect** 会根据文字判断语言。
- **Draft a script from source notes** 可以根据你粘贴的事实写出初稿，但只适用于使用你自己的密钥或程序的导演（见下一节）。点 **Draft from notes**，用之前请核对每一个事实。

## 选择谁来安排画面

- **Offline (free, private)** 把每句话里的词和你电脑上的图片配对，什么都不上传。
- **KinoDraw Cloud AI (your plan)** 把整篇讲稿发给 KinoDraw Cloud，由 AI 安排视频。云端允许时不需要账号；如果它要求登录，就在 **Settings** 里用 **Email me a code** 登录。它安排中文和英文视频，其他语言改为离线安排。
- 用你自己的 OpenAI、Anthropic 或 OpenAI 兼容服务的密钥：在 **Settings** → **Advanced directors** 里打开 **Show directors that use your own API key or program**。费用由服务商收取。密钥保存在电脑的钥匙串里。
- **Whole-story director v3**（默认打开）为整个视频安排角色、场景和风格。

## 选择风格和尺寸

- **Style** 决定画面风格：Whiteboard、Chalkboard、Notebook、Pixel Quest、Mosaic 或 Paper collage promo。**Choose for me** 让导演来选。选 Paper collage promo 或 **Choose for me** 时，还可以填写宣传用的 **Product name**、**Website** 和 **Button text**。
- **Format** 是横屏 16:9、竖屏 9:16 或方形 1:1，之后可以在项目里修改。
- 在项目里，画幅旁边的分辨率菜单决定制作和导出的尺寸：**Landscape 1080p**、**Landscape 4K**、**Square 1080** 或 **Portrait 1080**。

## 编辑分镜

![分镜：讲稿的每一部分和它的画面](media/guide/storyboard.jpg)

- 可以直接改一节的标题、它的短引语、要点便签，或图片下面的标签。
- 点一张图片可以换掉它，点 **+ Doodle** 添加一张，点 × 删除。箭头可以改变先画哪一张。
- 点 **Preview** 看那一刻的静止画面。
- **Undo** 和 **Redo** 撤销和重做修改。分镜会自动保存；**Save changes** 马上保存。
- **Versions** 保存有名字的版本：**Save named version** 保存，**Restore** 回到那个版本。
- **Rename**、**Duplicate** 和 **Trash** 作用于整个项目。侧边栏的 **Trash** 列出删除的项目，**Restore project** 可以恢复。
- **Re-plan visuals** 让所选的导演重新安排全部画面。

![Choose a doodle：搜索、图库、收藏和最近用过的图片](media/guide/choose-a-doodle.jpg)

在 **Choose a doodle** 里可以用视频的语言（中文、英文或西班牙文）搜索；英文的小拼写错误也能找到。上面的按钮一次显示一个图库（**Doodles**、**Fluent Emoji**、**Tabler Icons**、**Health Icons**）、你的 **★ Favourites**（点图片上的 ★）和 **Recent** 用过的图片。**More** 显示下一页。**Upload a picture** 可以加入你自己的 PNG、JPG 或 SVG（最大 10 MB），图片只保存在你的电脑上。

## 选择旁白

- **Built-in voice**：选一个声音，点 **Hear it** 试听，调整 **Speed**。在项目的 **Narrator** 标签里，**Pronunciations** 可以修正读音（每行一个：词 = 读法），然后点 **Save voice settings**。
- **My own voice**：用手机或任何录音设备把整篇讲稿读一遍。点 **Upload a recording**，再点 **Use it for this video**。录音里找不到的句子会被标出来；可以重录，或点 **Make the video anyway**。
- **Voice server**：在 **Settings** → **Voice server** 里填写你自己的 OpenAI 兼容语音服务的地址和模型，点 **Test**，打开 **Read scripts with my own OpenAI-compatible voice server**，再点 **Save**。

## 拿到视频

![Video 标签：做好的视频和它的文件](media/guide/video.jpg)

- 点 **Make video** 之后，**Video** 标签会播放 MP4，并给出 **Captions (.srt)**、**Chapters**、**Description**、**Transcript** 和 **Thumbnail**。**Open folder** 打开所有文件所在的文件夹。
- 每个视频默认以 2 秒的 “Made with KinoDraw” 卡片结尾。在项目里取消勾选就不加。
- **Export** 按你选的尺寸导出 **WebM with audio** 或 **GIF + audio companion**。
- **Project ZIP** 把整个项目打包成一个文件；**Import project ZIP…** 把它作为新项目打开。
- **Settings** → **Projects folder** 设置项目保存的位置。

## 键盘快捷键

- Ctrl+S（Mac 上 ⌘S）保存分镜；Ctrl+Z 撤销、Ctrl+Shift+Z 重做分镜修改（不在文本框里时）。
- Esc 关闭打开的窗口，比如 **Settings**；Tab 和 Shift+Tab 在控件之间移动，并停留在打开的窗口里。
- 按 ?（不在文本框里时）显示快捷键列表。**Help** 里也有 **Keyboard shortcuts** 按钮。

## 常见问题

> Pages files can’t be read. In Pages, choose File → Export To → Word…, then choose the .docx.

在 Pages 里把文稿导出为 Word，然后选择那个 .docx 文件。

> Make a video once, then you can hear every voice here.

声音会随这种语言的第一个视频下载。先做一个视频，**Hear it** 就能用了。

> Sign in to KinoDraw Cloud first (free: 5 AI videos a month), or choose Offline.

KinoDraw Cloud 需要用邮箱登录：打开 **Settings**，点 **Email me a code**，输入收到的验证码，再点 **Sign in**。或者选择 **Offline (free, private)**。

> Add your OpenAI key under Settings first.

在 **Settings** → **Advanced directors** 里保存你的密钥，或者换一个导演。

> checksum mismatch; download again

下载的文件在途中损坏了。再做一次视频，它会重新下载。

> … is too big (over 10 MB). Make it smaller and try again.

把图片存得小一些，或存成 JPG，再上传。

> Upload your recording first, or choose the built-in voice.

选了 **My own voice**，但还没有录音。在 **Narrator** 标签里上传录音，或选择 **Built-in voice**。

> … isn’t a recording we can play. Voice memos (.m4a), .mp3 and .wav files

把录音保存或导出为 M4A、MP3 或 WAV，再上传。

> Your recording does not sound like a reading of this script

照着讲稿原文，从头到尾在安静的地方录一遍。

> Part of the script seems to be missing from your recording

有一部分漏读了。每句话都读一遍，再上传新的录音。

> Your picture was not placed because the board changed while it uploaded. Choose it again under Your pictures.

上传图片时分镜改变了。再打开 **Choose a doodle**，在 **Your pictures** 下重新选它。

> KinoDraw couldn't bring over your Doodle Studio projects, voices and settings yet

关掉 Doodle Studio，然后关掉并重新打开 KinoDraw（如果一直出现，先重启电脑）。什么都没有被删除。

> Please tell us using "Feedback or a problem?".

出了意外的错误。点 **Feedback or a problem? Tell us**，说明你当时在做什么。

## 反馈和隐私

- **Feedback or a problem? Tell us** 在你点 **Send** 之前什么都不发送。点了之后，KinoDraw Cloud 会收到你写的和勾选的内容，以及应用版本、电脑类型、语言和安装 ID。
- 离线安排和内置声音不会把讲稿传出你的电脑。用 KinoDraw Cloud 或你自己的密钥安排画面时，讲稿会发给那个服务；语音服务会收到它要朗读的文字。
- 想让 KinoDraw Cloud 删除它保存的数据，请把这次安装的 ID（在 **Settings** → **KinoDraw Cloud** 里，或运行 `kinodraw cloud-id`）发邮件到 privacy@doodlecloud.org。详见[隐私政策](https://edwardaiwang-svg.github.io/kinodraw/privacy.html)。
