# 逐页 before/after 证据（每条都是本机栈实测 DOM）

| # | 路由 | 角色 | 改前 | 改后 |
|---|---|---|---|---|
| 1 | `/ledger/reimburse` | backoffice | HTTP 200 | HTTP 200 |
| 2 | `/my/calendar` | faculty | HTTP 200 | HTTP 200 |
| 3 | `/my/calendar` | parent | HTTP 200 | HTTP 200 |
| 4 | `/my/calendar` | student | HTTP 200 | HTTP 200 |
| 5 | `/my/calendar/new` | parent | HTTP 200 | HTTP 200 |
| 6 | `/my/calendar/new` | student | HTTP 200 | HTTP 200 |
| 7 | `/my/child` | parent | HTTP 200 | HTTP 200 |
| 8 | `/my/contacts` | student | HTTP 200 | HTTP 200 |
| 9 | `/my/evaluation/results` | faculty | HTTP 200 | HTTP 200 |
| 10 | `/my/fees` | faculty | HTTP 200 | HTTP 200 |
| 11 | `/my/study/46` | backoffice | HTTP 200 | HTTP 200 |
| 12 | `/my/study/46` | faculty | HTTP 200 | HTTP 200 |
| 13 | `/my/study/46` | parent | HTTP 200 | HTTP 200 |
| 14 | `/my/study/46` | student | HTTP 200 | HTTP 200 |
| 15 | `/registrar/subject/approvals` | faculty | HTTP 200 | HTTP 200 |
| 16 | `/student/timetable` | faculty | HTTP 200 | HTTP 200 |
| 17 | `/student/timetable` | parent | HTTP 200 | HTTP 200 |
| 18 | `/student/timetable` | student | HTTP 200 | HTTP 200 |

## 1. `/ledger/reimburse`（backoffice）

- 改前：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="alert alert-light border">该状态下暂无报销单。</div>
- 改后：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="alert alert-light border">该状态下暂无报销单。报销单由门户提交后进入本审批台；切换上方状态可看其他阶段的单据。</div>
- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 8）：改前 4 字 → 改后 34 字 ｜ 文本长度 改前 10 → 改后 42 ｜ records 改前 0 → 改后 0

## 2. `/my/calendar`（faculty）

- 改前：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="oe-empty"> <i class="fa fa-calendar" aria-hidden="true"></i> <p>本月暂无校历事项。</p> </div>
- 改后：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="oe-empty"> <i class="fa fa-calendar" aria-hidden="true"></i> <p>本月暂无校历事项。</p> <p class="small text-muted mb-2"> 校历事项（开学、考试、停课、活动）由教务处发布，发布后才会出现在这里； 上课安排不在校历里，要看每周课节请打开课表。 </p> <a class="btn btn-sm btn-light border" href="/student/timetable">查看课表</a> </div>
- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 8）：改前 2 字 → 改后 54 字 ｜ 文本长度 改前 9 → 改后 73 ｜ records 改前 0 → 改后 0

## 3. `/my/calendar`（parent）

- 改前：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="oe-empty"> <i class="fa fa-calendar" aria-hidden="true"></i> <p>本月暂无校历事项。</p> </div>
- 改后：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="oe-empty"> <i class="fa fa-calendar" aria-hidden="true"></i> <p>本月暂无校历事项。</p> <p class="small text-muted mb-2"> 校历事项（开学、考试、停课、活动）由教务处发布，发布后才会出现在这里； 上课安排不在校历里，要看每周课节请打开课表。 </p> <a class="btn btn-sm btn-light border" href="/student/timetable">查看课表</a> </div>
- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 8）：改前 2 字 → 改后 54 字 ｜ 文本长度 改前 9 → 改后 73 ｜ records 改前 0 → 改后 0

## 4. `/my/calendar`（student）

- 改前：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="oe-empty"> <i class="fa fa-calendar" aria-hidden="true"></i> <p>本月暂无校历事项。</p> </div>
- 改后：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="oe-empty"> <i class="fa fa-calendar" aria-hidden="true"></i> <p>本月暂无校历事项。</p> <p class="small text-muted mb-2"> 校历事项（开学、考试、停课、活动）由教务处发布，发布后才会出现在这里； 上课安排不在校历里，要看每周课节请打开课表。 </p> <a class="btn btn-sm btn-light border" href="/student/timetable">查看课表</a> </div>
- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 8）：改前 2 字 → 改后 54 字 ｜ 文本长度 改前 9 → 改后 73 ｜ records 改前 0 → 改后 0

## 5. `/my/calendar/new`（parent）

- 改前：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="oe-empty"> <i class="fa fa-calendar" aria-hidden="true"></i> <p>本月暂无校历事项。</p> </div>
- 改后：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="oe-empty"> <i class="fa fa-calendar" aria-hidden="true"></i> <p>本月暂无校历事项。</p> <p class="small text-muted mb-2"> 校历事项（开学、考试、停课、活动）由教务处发布，发布后才会出现在这里； 上课安排不在校历里，要看每周课节请打开课表。 </p> <a class="btn btn-sm btn-light border" href="/student/timetable">查看课表</a> </div>
- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 8）：改前 2 字 → 改后 54 字 ｜ 文本长度 改前 9 → 改后 73 ｜ records 改前 0 → 改后 0

## 6. `/my/calendar/new`（student）

- 改前：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="oe-empty"> <i class="fa fa-calendar" aria-hidden="true"></i> <p>本月暂无校历事项。</p> </div>
- 改后：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="oe-empty"> <i class="fa fa-calendar" aria-hidden="true"></i> <p>本月暂无校历事项。</p> <p class="small text-muted mb-2"> 校历事项（开学、考试、停课、活动）由教务处发布，发布后才会出现在这里； 上课安排不在校历里，要看每周课节请打开课表。 </p> <a class="btn btn-sm btn-light border" href="/student/timetable">查看课表</a> </div>
- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 8）：改前 2 字 → 改后 54 字 ｜ 文本长度 改前 9 → 改后 73 ｜ records 改前 0 → 改后 0

## 7. `/my/child`（parent）

- 改前：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="small text-muted"> 暂无已结束的评估记录（进行中的评估不在此处显示）。 </div>
- 改后：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="small text-muted"> 暂无已结束的评估记录（进行中的评估不在此处显示）。评估结束后会出现在这里。 </div>
- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 8）：改前 7 字 → 改后 18 字 ｜ 文本长度 改前 25 → 改后 37 ｜ records 改前 0 → 改后 0

## 8. `/my/contacts`（student）

- 改前：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="oe-norec"><i class="fa fa-users oe-norec-ic" aria-hidden="true"></i> <p class="oe-norec-txt">本班暂时还没有其他同学。</p></div>
- 改后：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="oe-norec"><i class="fa fa-users oe-norec-ic" aria-hidden="true"></i> <p class="oe-norec-txt"> 本班暂时还没有其他同学。同学名单来自教务的分班与选课， 分班后会自动出现在这里；如果你还没分班，请联系教务处。 </p></div>
- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 8）：改前 4 字 → 改后 42 字 ｜ 文本长度 改前 12 → 改后 55 ｜ records 改前 0 → 改后 0

## 9. `/my/evaluation/results`（faculty）

- 改前：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="alert alert-light border py-2 small"> 暂无已结束的评估结果。 </div>
- 改后：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="alert alert-light border py-2 small"> 暂无已结束的评估结果。评估结束（打分完成）后会在这里出现；进行中的评估不在本页显示。 </div>
- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 8）：改前 0 字 → 改后 27 字 ｜ 文本长度 改前 11 → 改后 42 ｜ records 改前 0 → 改后 0

## 10. `/my/fees`（faculty）

- 改前：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="alert alert-light border">暂无账单。</div>
- 改后：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="alert alert-light border"> 暂无账单。统筹费等应收账单由学坊登记（线下转账后记到账），登记后会出现在这里； 需要垫付报销时，点上方「发起报销」提交申请。 </div>
- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 8）：改前 0 字 → 改后 50 字 ｜ 文本长度 改前 5 → 改后 62 ｜ records 改前 0 → 改后 0

## 11. `/my/study/46`（backoffice）

- 改前：HTTP 200 ｜ records=0（空） ｜ DOM：<p class="ux3-hint">本科目暂无课程资料。教师上传后会出现在这里。</p>
- 改后：HTTP 200 ｜ records=0（空） ｜ DOM：<p class="ux3-hint">暂无成绩记录。任课教师录入并发布成绩后会显示在这里。</p>
- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 8）：改前 14 字 → 改后 18 字 ｜ 文本长度 改前 22 → 改后 26 ｜ records 改前 0 → 改后 0

## 12. `/my/study/46`（faculty）

- 改前：HTTP 200 ｜ records=0（空） ｜ DOM：<p class="ux3-hint">本科目暂无课程资料。教师上传后会出现在这里。</p>
- 改后：HTTP 200 ｜ records=0（空） ｜ DOM：<p class="ux3-hint">暂无成绩记录。任课教师录入并发布成绩后会显示在这里。</p>
- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 8）：改前 14 字 → 改后 18 字 ｜ 文本长度 改前 22 → 改后 26 ｜ records 改前 0 → 改后 0

## 13. `/my/study/46`（parent）

- 改前：HTTP 200 ｜ records=0（空） ｜ DOM：<p class="ux3-hint">本科目暂无课程资料。教师上传后会出现在这里。</p>
- 改后：HTTP 200 ｜ records=0（空） ｜ DOM：<p class="ux3-hint">暂无成绩记录。任课教师录入并发布成绩后会显示在这里。</p>
- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 8）：改前 14 字 → 改后 18 字 ｜ 文本长度 改前 22 → 改后 26 ｜ records 改前 0 → 改后 0

## 14. `/my/study/46`（student）

- 改前：HTTP 200 ｜ records=0（空） ｜ DOM：<p class="ux3-hint">本科目暂无课程资料。教师上传后会出现在这里。</p>
- 改后：HTTP 200 ｜ records=0（空） ｜ DOM：<p class="ux3-hint">暂无成绩记录。任课教师录入并发布成绩后会显示在这里。</p>
- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 8）：改前 14 字 → 改后 18 字 ｜ 文本长度 改前 22 → 改后 26 ｜ records 改前 0 → 改后 0

## 15. `/registrar/subject/approvals`（faculty）

- 改前：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="oe-norec"><i class="fa fa-check-circle oe-norec-ic" aria-hidden="true"></i> <p class="oe-norec-txt">没有符合条件的选课申请。</p></div>
- 改后：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="oe-norec"><i class="fa fa-check-circle oe-norec-ic" aria-hidden="true"></i> <p class="oe-norec-txt">没有符合条件的选课申请。换一个筛选条件可看其他状态的申请；学生提交选课申请后会进入这里。</p></div>
- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 8）：改前 0 字 → 改后 30 字 ｜ 文本长度 改前 12 → 改后 44 ｜ records 改前 0 → 改后 0

## 16. `/student/timetable`（faculty）

- 改前：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="timetable_schedule_portal active"> <div class="alert alert-info mb-0"> 这一周暂无排课记录。 </div> </div>
- 改后：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="timetable_schedule_portal active"> <div class="alert alert-info mb-0"> 这一周暂无排课记录。 本周没有你的课节。课表按教务处的排课生成：还没排到你的课时，这里就是空的； 如果应该有课却没显示，请联系教务处核对排课。 </div> </div>
- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 8）：改前 3 字 → 改后 56 字 ｜ 文本长度 改前 10 → 改后 71 ｜ records 改前 0 → 改后 0

## 17. `/student/timetable`（parent）

- 改前：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="timetable_schedule_portal active"> <div class="alert alert-info mb-0"> 这一周暂无排课记录。 </div> </div>
- 改后：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="timetable_schedule_portal active"> <div class="alert alert-info mb-0"> 这一周暂无排课记录。 孩子的课表按班级生成：孩子还没分班、或本周尚未排课时，这里就是空的。 分班与排课由教务在开学时完成；可到孩子仪表盘确认分班与选课情况。 <a class="alert-link ms-1" href="/my/child">查看我的孩子</a> </div> </div>
- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 8）：改前 3 字 → 改后 64 字 ｜ 文本长度 改前 10 → 改后 85 ｜ records 改前 0 → 改后 0

## 18. `/student/timetable`（student）

- 改前：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="timetable_schedule_portal active"> <div class="alert alert-info mb-0"> 这一周暂无排课记录。 </div> </div>
- 改后：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="timetable_schedule_portal active"> <div class="alert alert-info mb-0"> 这一周暂无排课记录。 课表按你所在的班级生成：还没分班、或本周尚未排课时，这里就是空的。 分班与排课由教务在开学时完成，排好后会自动出现； 想先确认自己的选课，可去报课选科。 <a class="alert-link ms-1" href="/subject/enroll">去报课选科</a> </div> </div>
- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 8）：改前 3 字 → 改后 69 字 ｜ 文本长度 改前 10 → 改后 93 ｜ records 改前 0 → 改后 0

