# 逐页 before/after 证据（每条都是本机栈实测 DOM）

| # | 路由 | 角色 | 改前 | 改后 |
|---|---|---|---|---|
| 1 | `/my/calendar` | first | HTTP 200 | HTTP 200 |
| 2 | `/my/calendar/new` | first | HTTP 200 | HTTP 200 |
| 3 | `/my/contacts` | first | HTTP 200 | HTTP 200 |
| 4 | `/my/courses` | first | HTTP 200 | HTTP 200 |
| 5 | `/my/courses/46` | first | HTTP 200 | HTTP 200 |
| 6 | `/my/courses/46/rep` | first | HTTP 200 | HTTP 200 |
| 7 | `/my/courses/lesson/1` | first | HTTP 200 | HTTP 200 |
| 8 | `/my/fees` | first | HTTP 200 | HTTP 200 |
| 9 | `/student/assignment/details` | first | HTTP 200 | HTTP 200 |
| 10 | `/student/attendance` | first | HTTP 200 | HTTP 200 |
| 11 | `/student/exam` | first | HTTP 200 | HTTP 200 |
| 12 | `/student/profile` | first | HTTP 500 | HTTP 200 |
| 13 | `/student/timetable` | first | HTTP 200 | HTTP 200 |

## 1. `/my/calendar`（first）

- 改前：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="oe-empty"> <i class="fa fa-calendar" aria-hidden="true"></i> <p>本月暂无校历事项。</p> </div>
- 改后：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="oe-empty"> <i class="fa fa-calendar" aria-hidden="true"></i> <p>本月暂无校历事项。</p> <p class="small text-muted mb-2"> 校历事项（开学、考试、停课、活动）由教务处发布，发布后才会出现在这里； 上课安排不在校历里，要看每周课节请打开课表。 </p> <a class="btn btn-sm btn-light border" href="/student/timetable">查看课表</a> </div>
- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 8）：改前 2 字 → 改后 54 字 ｜ 文本长度 改前 9 → 改后 73 ｜ records 改前 0 → 改后 0

## 2. `/my/calendar/new`（first）

- 改前：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="oe-empty"> <i class="fa fa-calendar" aria-hidden="true"></i> <p>本月暂无校历事项。</p> </div>
- 改后：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="oe-empty"> <i class="fa fa-calendar" aria-hidden="true"></i> <p>本月暂无校历事项。</p> <p class="small text-muted mb-2"> 校历事项（开学、考试、停课、活动）由教务处发布，发布后才会出现在这里； 上课安排不在校历里，要看每周课节请打开课表。 </p> <a class="btn btn-sm btn-light border" href="/student/timetable">查看课表</a> </div>
- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 8）：改前 2 字 → 改后 54 字 ｜ 文本长度 改前 9 → 改后 73 ｜ records 改前 0 → 改后 0

## 3. `/my/contacts`（first）

- 改前：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="oe-norec"><i class="fa fa-users oe-norec-ic" aria-hidden="true"></i> <p class="oe-norec-txt">本班暂时还没有其他同学。</p></div>
- 改后：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="oe-norec"><i class="fa fa-users oe-norec-ic" aria-hidden="true"></i> <p class="oe-norec-txt"> 本班暂时还没有其他同学。同学名单来自教务的分班与选课， 分班后会自动出现在这里；如果你还没分班，请联系教务处。 </p></div>
- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 8）：改前 4 字 → 改后 42 字 ｜ 文本长度 改前 12 → 改后 55 ｜ records 改前 0 → 改后 0

## 4. `/my/courses`（first）

- 改前：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="alert alert-info">暂无可学课程。</div>
- 改后：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="alert alert-info"> 暂无可学课程。这里按你的在修科目展示课次：报课通过、科目生效后会自动出现。 <a class="alert-link ms-1" href="/subject/enroll">去报课选科</a> </div>
- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 8）：改前 0 字 → 改后 32 字 ｜ 文本长度 改前 7 → 改后 43 ｜ records 改前 0 → 改后 0

## 5. `/my/courses/46`（first）

- 改前：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="alert alert-info">暂无可学课程。</div>
- 改后：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="alert alert-info"> 暂无可学课程。这里按你的在修科目展示课次：报课通过、科目生效后会自动出现。 <a class="alert-link ms-1" href="/subject/enroll">去报课选科</a> </div>
- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 8）：改前 0 字 → 改后 32 字 ｜ 文本长度 改前 7 → 改后 43 ｜ records 改前 0 → 改后 0

## 6. `/my/courses/46/rep`（first）

- 改前：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="alert alert-info">暂无可学课程。</div>
- 改后：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="alert alert-info"> 暂无可学课程。这里按你的在修科目展示课次：报课通过、科目生效后会自动出现。 <a class="alert-link ms-1" href="/subject/enroll">去报课选科</a> </div>
- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 8）：改前 0 字 → 改后 32 字 ｜ 文本长度 改前 7 → 改后 43 ｜ records 改前 0 → 改后 0

## 7. `/my/courses/lesson/1`（first）

- 改前：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="alert alert-info">暂无可学课程。</div>
- 改后：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="alert alert-info"> 暂无可学课程。这里按你的在修科目展示课次：报课通过、科目生效后会自动出现。 <a class="alert-link ms-1" href="/subject/enroll">去报课选科</a> </div>
- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 8）：改前 0 字 → 改后 32 字 ｜ 文本长度 改前 7 → 改后 43 ｜ records 改前 0 → 改后 0

## 8. `/my/fees`（first）

- 改前：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="alert alert-light border">暂无账单。</div>
- 改后：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="alert alert-light border"> 暂无账单。统筹费等应收账单由学坊登记（线下转账后记到账），登记后会出现在这里； 需要垫付报销时，点上方「发起报销」提交申请。 </div>
- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 8）：改前 0 字 → 改后 50 字 ｜ 文本长度 改前 5 → 改后 62 ｜ records 改前 0 → 改后 0

## 9. `/student/assignment/details`（first）

- 改前：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="alert alert-info">暂无作业记录。</div>
- 改后：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="alert alert-info"> 暂无作业记录。作业由任课教师在课程里发布，发布后这里会显示截止时间与提交状态； 如果你还没有在修科目，先去课程中心看看。 <a class="alert-link ms-1" href="/my/study">去课程中心</a> </div>
- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 8）：改前 0 字 → 改后 46 字 ｜ 文本长度 改前 7 → 改后 66 ｜ records 改前 0 → 改后 0

## 10. `/student/attendance`（first）

- 改前：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="alert alert-info">暂无考勤记录。</div>
- 改后：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="alert alert-info"> 暂无考勤记录。考勤由任课老师每次上课时登记，登记后会按课节显示在这里； 如果课表也还是空的，请先确认自己的排课情况。 <a class="alert-link ms-1" href="/student/timetable">查看我的课表</a> </div>
- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 8）：改前 0 字 → 改后 52 字 ｜ 文本长度 改前 7 → 改后 65 ｜ records 改前 0 → 改后 0

## 11. `/student/exam`（first）

- 改前：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="alert alert-info">暂无考试记录。</div>
- 改后：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="alert alert-info"> 暂无考试记录。考试由任课教师在课程中安排，成绩录入后这里会按场次显示得分与等级； 如果你还没有在修科目，先去课程中心看看。 <a class="alert-link ms-1" href="/my/study">去课程中心</a> </div>
- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 8）：改前 0 字 → 改后 47 字 ｜ 文本长度 改前 7 → 改后 67 ｜ records 改前 0 → 改后 0

## 12. `/student/profile`（first）

- 改前：HTTP 500 ｜ records=0（空） ｜ DOM：（本页没有可识别的空态块）
- 改后：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="oe-empty"><i class="fa fa-users"></i><p>暂未登记家长/紧急联系人信息。请把家长或紧急联系人的姓名与电话交给教务处登记，便于紧急情况联系。</p></div>
- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 8）：改前 0 字 → 改后 31 字 ｜ 文本长度 改前 0 → 改后 48 ｜ records 改前 0 → 改后 0

## 13. `/student/timetable`（first）

- 改前：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="timetable_schedule_portal active"> <div class="alert alert-info mb-0"> 这一周暂无排课记录。 </div> </div>
- 改后：HTTP 200 ｜ records=0（空） ｜ DOM：<div class="timetable_schedule_portal active"> <div class="alert alert-info mb-0"> 这一周暂无排课记录。 课表按你所在的班级生成：还没分班、或本周尚未排课时，这里就是空的。 分班与排课由教务在开学时完成，排好后会自动出现； 想先确认自己的选课，可去报课选科。 <a class="alert-link ms-1" href="/subject/enroll">去报课选科</a> </div> </div>
- 判据读数（E1 = 切掉「没有 X」后的信息量，阈值 8）：改前 3 字 → 改后 69 字 ｜ 文本长度 改前 10 → 改后 93 ｜ records 改前 0 → 改后 0

