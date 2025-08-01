"""
调度管理器 - 基于 APScheduler 的任务调度系统
提供统一的调度接口，支持定时任务、间隔任务、一次性任务等
"""

import asyncio
from typing import Any, Callable, Dict, List, Optional, Union
from datetime import datetime, timedelta
from functools import wraps
import threading
from contextlib import contextmanager
from leek_core.utils import get_logger

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ThreadPoolExecutor, ProcessPoolExecutor
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, JobExecutionEvent

logger = get_logger(__name__)


class SchedulerManager:
    """调度管理器"""

    def __init__(
        self,
        jobstores: Optional[Dict[str, Any]] = None,
        executors: Optional[Dict[str, Any]] = None,
        job_defaults: Optional[Dict[str, Any]] = None,
        timezone: str = "Asia/Shanghai",
    ):
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._job_count = 0
        self._running = False
        self.initialize(jobstores, executors, job_defaults, timezone)

    def initialize(
        self,
        jobstores: Optional[Dict[str, Any]] = None,
        executors: Optional[Dict[str, Any]] = None,
        job_defaults: Optional[Dict[str, Any]] = None,
        timezone: str = "Asia/Shanghai",
    ) -> None:
        """
        初始化调度器

        Args:
            jobstores: 任务存储配置
            executors: 执行器配置
            job_defaults: 默认任务配置
            timezone: 时区
            daemon: 是否守护进程
        """
        if self._scheduler is not None:
            logger.warning("调度器已经初始化")
            return

        # 默认配置
        if jobstores is None:
            jobstores = {"default": MemoryJobStore()}

        if executors is None:
            executors = {
                "default": AsyncIOExecutor(),  # 使用 AsyncIOExecutor 作为默认执行器
            }

        if job_defaults is None:
            job_defaults = {
                "coalesce": True,  # 合并延迟的任务
                "max_instances": 1,
                "misfire_grace_time": 5,
            }

        # 创建调度器
        self._scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults,
            timezone=timezone,
        )

        # 添加事件监听器
        self._scheduler.add_listener(self._job_executed_listener, EVENT_JOB_EXECUTED)
        self._scheduler.add_listener(self._job_error_listener, EVENT_JOB_ERROR)

        logger.info("调度管理器初始化完成")

    def start(self) -> None:
        """启动调度器"""
        if self._scheduler is None:
            raise RuntimeError("调度器未初始化，请先调用 initialize() 方法")

        if self._running:
            logger.warning("调度器已经在运行")
            return

        self._scheduler.start()
        self._running = True
        logger.info("调度器已启动")

    def shutdown(self, wait: bool = True) -> None:
        """关闭调度器"""
        if self._scheduler is None or not self._running:
            return

        self._scheduler.shutdown(wait=wait)
        self._running = False
        logger.info("调度器已关闭")

    def add_job(
        self,
        func: Callable,
        trigger: Union[str, CronTrigger, IntervalTrigger, DateTrigger],
        args: Optional[tuple] = None,
        kwargs: Optional[dict] = None,
        id: Optional[str] = None,
        name: Optional[str] = None,
        **trigger_args,
    ) -> str:
        """
        添加任务

        Args:
            func: 要执行的函数
            trigger: 触发器类型或触发器对象
            args: 函数参数
            kwargs: 函数关键字参数
            id: 任务ID
            name: 任务名称
            **trigger_args: 触发器参数

        Returns:
            任务ID
        """
        if self._scheduler is None:
            raise RuntimeError("调度器未初始化")

        # 生成任务ID
        if id is None:
            self._job_count += 1
            id = f"job_{self._job_count}"

        # 添加任务
        job = self._scheduler.add_job(
            func=func,
            trigger=trigger,
            args=args,
            kwargs=kwargs,
            id=id,
            name=name,
            **trigger_args,
        )

        logger.info(f"任务已添加: {id} ({name or func.__name__})")
        return job.id

    def add_cron_job(
        self,
        func: Callable,
        year: Optional[Union[int, str]] = None,
        month: Optional[Union[int, str]] = None,
        day: Optional[Union[int, str]] = None,
        week: Optional[Union[int, str]] = None,
        day_of_week: Optional[Union[int, str]] = None,
        hour: Optional[Union[int, str]] = None,
        minute: Optional[Union[int, str]] = None,
        second: Optional[Union[int, str]] = None,
        start_date: Optional[Union[str, datetime]] = None,
        end_date: Optional[Union[str, datetime]] = None,
        timezone: Optional[str] = None,
        args: Optional[tuple] = None,
        kwargs: Optional[dict] = None,
        id: Optional[str] = None,
        name: Optional[str] = None,
    ) -> str:
        """
        添加 Cron 定时任务

        Args:
            func: 要执行的函数
            year, month, day, week, day_of_week, hour, minute, second: 时间参数
            start_date: 开始时间
            end_date: 结束时间
            timezone: 时区
            args: 函数参数
            kwargs: 函数关键字参数
            id: 任务ID
            name: 任务名称

        Returns:
            任务ID
        """
        return self.add_job(
            func=func,
            trigger="cron",
            year=year,
            month=month,
            day=day,
            week=week,
            day_of_week=day_of_week,
            hour=hour,
            minute=minute,
            second=second,
            start_date=start_date,
            end_date=end_date,
            timezone=timezone,
            args=args,
            kwargs=kwargs,
            id=id,
            name=name,
        )

    def add_interval_job(
        self,
        func: Callable,
        weeks: int = 0,
        days: int = 0,
        hours: int = 0,
        minutes: int = 0,
        seconds: int = 0,
        start_date: Optional[Union[str, datetime]] = None,
        end_date: Optional[Union[str, datetime]] = None,
        timezone: Optional[str] = None,
        args: Optional[tuple] = None,
        kwargs: Optional[dict] = None,
        id: Optional[str] = None,
        name: Optional[str] = None,
    ) -> str:
        """
        添加间隔任务

        Args:
            func: 要执行的函数
            weeks, days, hours, minutes, seconds: 间隔时间
            start_date: 开始时间
            end_date: 结束时间
            timezone: 时区
            args: 函数参数
            kwargs: 函数关键字参数
            id: 任务ID
            name: 任务名称

        Returns:
            任务ID
        """
        return self.add_job(
            func=func,
            trigger="interval",
            weeks=weeks,
            days=days,
            hours=hours,
            minutes=minutes,
            seconds=seconds,
            start_date=start_date,
            end_date=end_date,
            timezone=timezone,
            args=args,
            kwargs=kwargs,
            id=id,
            name=name,
        )

    def add_date_job(
        self,
        func: Callable,
        run_date: Union[str, datetime],
        timezone: Optional[str] = None,
        args: Optional[tuple] = None,
        kwargs: Optional[dict] = None,
        id: Optional[str] = None,
        name: Optional[str] = None,
    ) -> str:
        """
        添加一次性任务

        Args:
            func: 要执行的函数
            run_date: 执行时间
            timezone: 时区
            args: 函数参数
            kwargs: 函数关键字参数
            id: 任务ID
            name: 任务名称

        Returns:
            任务ID
        """
        return self.add_job(
            func=func,
            trigger="date",
            run_date=run_date,
            timezone=timezone,
            args=args,
            kwargs=kwargs,
            id=id,
            name=name,
        )

    def remove_job(self, job_id: str) -> None:
        """移除任务"""
        if self._scheduler is None:
            raise RuntimeError("调度器未初始化")

        self._scheduler.remove_job(job_id)
        logger.info(f"任务已移除: {job_id}")

    def get_job(self, job_id: str):
        """获取任务"""
        if self._scheduler is None:
            raise RuntimeError("调度器未初始化")

        return self._scheduler.get_job(job_id)

    def get_jobs(self) -> List:
        """获取所有任务"""
        if self._scheduler is None:
            raise RuntimeError("调度器未初始化")

        return self._scheduler.get_jobs()

    def pause_job(self, job_id: str) -> None:
        """暂停任务"""
        if self._scheduler is None:
            raise RuntimeError("调度器未初始化")

        self._scheduler.pause_job(job_id)
        logger.info(f"任务已暂停: {job_id}")

    def resume_job(self, job_id: str) -> None:
        """恢复任务"""
        if self._scheduler is None:
            raise RuntimeError("调度器未初始化")

        self._scheduler.resume_job(job_id)
        logger.info(f"任务已恢复: {job_id}")

    def modify_job(self, job_id: str, **kwargs) -> None:
        """修改任务"""
        if self._scheduler is None:
            raise RuntimeError("调度器未初始化")

        self._scheduler.modify_job(job_id, **kwargs)
        logger.info(f"任务已修改: {job_id}")

    def reschedule_job(
        self,
        job_id: str,
        trigger: Union[str, CronTrigger, IntervalTrigger, DateTrigger],
        **trigger_args,
    ) -> None:
        """重新调度任务"""
        if self._scheduler is None:
            raise RuntimeError("调度器未初始化")

        self._scheduler.reschedule_job(job_id, trigger=trigger, **trigger_args)
        logger.info(f"任务已重新调度: {job_id}")

    def run_job(self, job_id: str) -> None:
        """立即运行任务"""
        if self._scheduler is None:
            raise RuntimeError("调度器未初始化")

        # 获取任务
        job = self._scheduler.get_job(job_id)
        if job is None:
            raise ValueError(f"任务不存在: {job_id}")
        
        # 直接执行任务函数
        try:
            logger.info(f"开始立即运行任务: {job_id}")
            result = job.func(*job.args, **job.kwargs)
            
            # 检查是否是异步函数
            if asyncio.iscoroutine(result):
                logger.warning(f"任务 {job_id} 是异步函数，但使用了同步调用方式")
            
            logger.info(f"任务立即运行完成: {job_id}")
            return result
        except Exception as e:
            logger.error(f"任务立即运行失败: {job_id}, 错误: {str(e)}")
            raise

    async def run_job_async(self, job_id: str) -> None:
        """异步立即运行任务"""
        if self._scheduler is None:
            raise RuntimeError("调度器未初始化")

        # 获取任务
        job = self._scheduler.get_job(job_id)
        if job is None:
            raise ValueError(f"任务不存在: {job_id}")
        
        # 执行任务函数
        try:
            logger.info(f"开始异步立即运行任务: {job_id}")
            result = job.func(*job.args, **job.kwargs)
            
            # 如果是异步函数，等待执行完成
            if asyncio.iscoroutine(result):
                result = await result
            
            logger.info(f"异步任务立即运行完成: {job_id}")
            return result
        except Exception as e:
            logger.error(f"异步任务立即运行失败: {job_id}, 错误: {str(e)}")
            raise

    def is_running(self) -> bool:
        """检查调度器是否运行"""
        return self._running and self._scheduler is not None and self._scheduler.running

    def get_job_count(self) -> int:
        """获取任务数量"""
        if self._scheduler is None:
            return 0
        return len(self._scheduler.get_jobs())

    @contextmanager
    def job_context(self, job_id: str):
        """任务上下文管理器"""
        try:
            yield
        except Exception as e:
            logger.error(f"任务 {job_id} 执行出错: {str(e)}", exc_info=True)
            raise

    def _job_executed_listener(self, event: JobExecutionEvent) -> None:
        """任务执行成功监听器"""
        logger.info(f"任务执行成功: {event.job_id} ({event.jobstore})")

    def _job_error_listener(self, event: JobExecutionEvent) -> None:
        """任务执行错误监听器"""
        logger.error(
            f"任务执行失败: {event.job_id}, 错误: {event.exception}, 回溯: {event.traceback}"
        )


# 全局调度管理器实例
scheduler = SchedulerManager()


# 便捷函数
def get_scheduler() -> SchedulerManager:
    """获取调度管理器实例"""
    return scheduler


def schedule_job(
    trigger: Union[str, CronTrigger, IntervalTrigger, DateTrigger], **trigger_args
):
    """
    任务调度装饰器

    Usage:
        @schedule_job('interval', minutes=5)
        def my_task():
            pass

        @schedule_job('cron', hour=9, minute=30)
        def daily_task():
            pass
    """

    def decorator(func: Callable) -> Callable:
        scheduler.add_job(func, trigger, **trigger_args)
        return func

    return decorator


def schedule_cron(**cron_args):
    """Cron 任务装饰器"""
    return schedule_job("cron", **cron_args)


def schedule_interval(**interval_args):
    """间隔任务装饰器"""
    return schedule_job("interval", **interval_args)


def schedule_date(**date_args):
    """一次性任务装饰器"""
    return schedule_job("date", **date_args)
